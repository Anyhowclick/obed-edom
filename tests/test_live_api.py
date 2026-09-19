from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from obed_edom.live_host import OutputDisplay
from obed_edom.live_session import LiveSessionService, PlayerObservation
from obed_edom.web import live


class Adapter:
    output = {'width': 1920, 'height': 1080}

    def __init__(self, *args, **kwargs):
        self.visible = False
        self.clicks = 0

    def capabilities(self):
        return {op: {'supported': True} for op in ('advance', 'goTo', 'hide', 'show')}

    def observe(self):
        return PlayerObservation(original_slide=1 + self.clicks, scene_id=str(self.clicks), output_visible=self.visible)

    def execute(self, operation, slide=None):
        if operation == 'advance':
            self.clicks += 1
        elif operation in ('hide', 'show'):
            self.visible = operation == 'show'
        return self.observe()

    def stop(self):
        pass


def client_for(tmp_path, monkeypatch):
    thumb = tmp_path / 'thumbnail.jpeg'
    thumb.write_bytes(b'jpeg')
    job = SimpleNamespace(id='prepared', kind='html-preview', status='done', result={
        'phase': 'ready', 'path': '/example/deck.key', 'exportKey': 'key',
        'sourceDigest': 'source', 'manifest': {'playerDigest': live.PLAYER_SHA256},
        'slides': [{'originalOrdinal': 1, 'playerIndex': 0, 'exportedUuid': 'uuid', 'skipped': False}],
    })
    runner = SimpleNamespace(get=lambda key: job if key == job.id else None,
                             list=lambda **kwargs: [job])
    monkeypatch.setattr(live, 'registered_export_root', lambda *_: tmp_path)
    monkeypatch.setattr(live, 'safe_export_file', lambda *_: thumb)
    monkeypatch.setattr(live, 'file_sha256', lambda *_: live.PLAYER_SHA256)
    monkeypatch.setattr(live, 'load_header', lambda *_: ({'slideWidth': 1920, 'slideHeight': 1080, 'showMode': 0}, 'header.json'))
    claims, releases = [], []
    service = LiveSessionService(claim=lambda *args: claims.append(args), release=lambda *args: releases.append(args))
    app = FastAPI()
    app.include_router(live.live_router(runner, service=service, host_factory=Adapter,
        displays=lambda: [OutputDisplay(42, 1920, 0, 2560, 1440, False)]))
    return TestClient(app, base_url='http://127.0.0.1'), claims, releases, job


def test_live_api_session_survives_presenter_and_rejects_duplicate_start(tmp_path, monkeypatch):
    client, claims, releases, _ = client_for(tmp_path, monkeypatch)
    assert client.get('/api/live').json() is None
    assert client.get('/api/live/displays').json()[0]['id'] == '42'
    assert client.get('/api/live/decks').json()[0]['previewJobId'] == 'prepared'
    state = client.post('/api/live', json={'previewJobId': 'prepared', 'displayId': '42'}).json()
    session = state['sessionId']
    assert not state['outputVisible']
    assert client.get(state['slides'][0]['thumbnailUrl']).content == b'jpeg'
    assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 409
    assert client.get('/api/live').json()['sessionId'] == session
    command = {'requestId': 'click', 'operation': 'advance'}
    first = client.post(f'/api/live/{session}/commands', json=command).json()
    duplicate = client.post(f'/api/live/{session}/commands', json=command).json()
    assert first == duplicate
    assert first['state']['originalSlide'] == 2
    client.post(f'/api/live/{session}/commands', json={'requestId': 'stop', 'operation': 'stop'})
    assert len(claims) == len(releases) == 1
    assert client.get(state['slides'][0]['thumbnailUrl']).status_code == 404


def test_live_api_refuses_unqualified_export_and_cross_origin(tmp_path, monkeypatch):
    client, claims, _, job = client_for(tmp_path, monkeypatch)
    assert client.post('/api/live', headers={'origin': 'https://evil.example'}, json={'previewJobId': 'prepared'}).status_code == 403
    job.result['manifest']['playerDigest'] = 'changed'
    response = client.post('/api/live', json={'previewJobId': 'prepared'})
    assert response.status_code == 409
    assert not claims


def test_live_api_rejects_non_integer_go_to(tmp_path, monkeypatch):
    client, _, _, _ = client_for(tmp_path, monkeypatch)
    assert client.post('/api/live/stale/commands', json={'requestId': 'x', 'operation': 'goTo', 'slide': True}).status_code == 422


def test_review_cleanup_retains_active_program_assets(tmp_path, monkeypatch):
    from obed_edom import html_preview as hp
    from tests.test_html_preview import _digest

    monkeypatch.setenv('OBED_EDOM_OUTPUT_ROOT', str(tmp_path))
    digest = _digest('live-asset-ownership')
    key = hp.cache_key(digest)
    folder, root = hp.reject_unresolved_cache_symlinks(digest)
    root.mkdir(parents=True)
    (root / 'index.html').write_text('fixture')
    hp.claim_export(key, 'preview-owner', {})
    service = LiveSessionService()
    state = service.start(Adapter(), export_key=key, export_root=root,
                          identity={'sourceDigest': digest, 'slides': []})
    result = hp.cleanup_preview('preview-owner', {'exportKey': key, 'sourceDigest': digest,
                                                 'exportRoot': str(root)})
    assert result['retained']
    assert root.exists()
    assert hp.job_owns_export(key, state['sessionId'])
    service.command(state['sessionId'], 'stop', 'stop')
    assert not hp.job_owns_export(key, state['sessionId'])


def test_dashboard_shutdown_stops_owned_session(tmp_path, monkeypatch):
    client, claims, releases, _ = client_for(tmp_path, monkeypatch)
    with client:
        assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200
        assert len(claims) == 1 and not releases
    assert len(releases) == 1


def test_live_api_rejects_foreign_host_even_when_origin_matches(tmp_path, monkeypatch):
    client, claims, _, _ = client_for(tmp_path, monkeypatch)
    response = client.post('/api/live', headers={'host': 'evil.example', 'origin': 'http://evil.example'},
                           json={'previewJobId': 'prepared'})
    assert response.status_code == 403
    assert not claims
