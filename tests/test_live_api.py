import hashlib
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from obed_edom import live_runtime
from obed_edom.live_host import LiveOutputHost, OutputDisplay
from obed_edom.live_session import LiveSessionService, PlayerObservation
from obed_edom.web import live


class Adapter:
    output = {'width': 1920, 'height': 1080}

    def __init__(self, *args, **kwargs):
        self.visible = False
        self.clicks = 0
        self.wait: Event | None = None
        self.release: Event | None = None
        self.stopped = False

    def capabilities(self):
        return {op: {'supported': True} for op in ('advance', 'goTo', 'hide', 'show')}

    def observe(self):
        return PlayerObservation(original_slide=1 + self.clicks, scene_id=str(self.clicks), output_visible=self.visible)

    def execute(self, operation, slide=None):
        if self.wait:
            self.wait.set()
            assert self.release
            self.release.wait(2)
            if self.stopped:
                raise RuntimeError('player stopped')
        if operation == 'advance':
            self.clicks += 1
        elif operation in ('hide', 'show'):
            self.visible = operation == 'show'
        return self.observe()

    def stop(self):
        self.stopped = True
        if self.release:
            self.release.set()


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
    adapters = []

    def host_factory(*args, **kwargs):
        adapter = Adapter(*args, **kwargs)
        adapters.append(adapter)
        return adapter

    app = FastAPI()
    app.include_router(live.live_router(runner, service=service, host_factory=host_factory,
        displays=lambda: [OutputDisplay(42, 1920, 0, 2560, 1440, False)]))
    return TestClient(app, base_url='http://127.0.0.1'), claims, releases, job, adapters, service


def test_live_api_session_survives_presenter_and_rejects_duplicate_start(tmp_path, monkeypatch):
    client, claims, releases, _, _adapters, _service = client_for(tmp_path, monkeypatch)
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
    client, claims, _, job, _adapters, _service = client_for(tmp_path, monkeypatch)
    assert client.post('/api/live', headers={'origin': 'https://evil.example'}, json={'previewJobId': 'prepared'}).status_code == 403
    job.result['manifest']['playerDigest'] = 'changed'
    response = client.post('/api/live', json={'previewJobId': 'prepared'})
    assert response.status_code == 409
    assert not claims


def test_live_api_rejects_non_integer_go_to(tmp_path, monkeypatch):
    client, _, _, _, _adapters, _service = client_for(tmp_path, monkeypatch)
    state = client.post('/api/live', json={'previewJobId': 'prepared'}).json()
    session = state['sessionId']
    response = client.post(f'/api/live/{session}/commands', json={'requestId': 'x', 'operation': 'goTo', 'slide': True})
    assert response.status_code == 422


def test_live_api_rejects_unknown_operation(tmp_path, monkeypatch):
    client, _, _, _, _adapters, _service = client_for(tmp_path, monkeypatch)
    state = client.post('/api/live', json={'previewJobId': 'prepared'}).json()
    session = state['sessionId']
    response = client.post(f'/api/live/{session}/commands', json={'requestId': 'x', 'operation': 'bogus'})
    assert response.status_code == 422


def test_thumbnail_missing_original_ordinal_key_returns_404(tmp_path, monkeypatch):
    client, _, _, _, _adapters, service = client_for(tmp_path, monkeypatch)
    state = client.post('/api/live', json={'previewJobId': 'prepared'}).json()
    session = state['sessionId']
    service._session.state['slides'] = [{'skipped': False, 'exportedUuid': 'x'}]
    response = client.get(f'/api/live/{session}/thumbnail/1')
    assert response.status_code == 404


def test_dashboard_shutdown_stops_session_with_command_in_flight(tmp_path, monkeypatch):
    client, _claims, releases, _, adapters, _service = client_for(tmp_path, monkeypatch)
    with client:
        assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200
        adapter = adapters[-1]
        adapter.wait = Event()
        adapter.release = Event()
        session = client.get('/api/live').json()['sessionId']
        responses = []
        thread = Thread(target=lambda: responses.append(
            client.post(f'/api/live/{session}/commands', json={'requestId': 'a', 'operation': 'advance'}).json()
        ))
        thread.start()
        assert adapter.wait.wait(1)
    thread.join(2)
    assert not thread.is_alive()
    assert len(releases) == 1
    assert responses[0]['outcome'] == 'rejected'


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
    client, claims, releases, _, _adapters, _service = client_for(tmp_path, monkeypatch)
    with client:
        assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200
        assert len(claims) == 1 and not releases
    assert len(releases) == 1


def test_live_api_rejects_foreign_host_even_when_origin_matches(tmp_path, monkeypatch):
    client, claims, _, _, _adapters, _service = client_for(tmp_path, monkeypatch)
    response = client.post('/api/live', headers={'host': 'evil.example', 'origin': 'http://evil.example'},
                           json={'previewJobId': 'prepared'})
    assert response.status_code == 403
    assert not claims


class FakeAttachCdp:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
    def start(self): pass
    def goto(self, url): pass
    def stop(self): pass
    def evaluate(self, expression):
        if '__obedLive' in expression:
            return {'exportedSlideIndex': 0, 'sceneId': '0', 'buildIndex': None, 'revision': 1, 'canAdvance': True, 'canGoTo': True, 'ready': True, 'busy': False}
        if "getElementById('body')" in expression:
            return False
        return [1920, 1080]
    def key(self, *_args): pass


class FakeAttachServer:
    def __init__(self, *_args, **_kwargs): pass
    def start(self): return 'http://program.test/program.html'
    def stop(self): pass


def test_live_api_attach_mode_starts_without_consulting_displays(tmp_path, monkeypatch):
    monkeypatch.setenv('OBED_EDOM_OUTPUT_ROOT', str(tmp_path / 'out'))
    monkeypatch.setenv('OBED_LIVE_ATTACH', 'http://127.0.0.1:9222')
    root = tmp_path / 'out' / '.html-preview' / 'export'
    (root / 'assets' / 'player').mkdir(parents=True)
    player_bytes = b'before;' + live_runtime._ANCHOR + b';after'
    (root / 'assets' / 'player' / 'main.js').write_bytes(player_bytes)
    (root / 'assets' / 'header.json').write_text('{"slideWidth":1920,"slideHeight":1080,"showMode":0}')
    monkeypatch.setattr(live_runtime, 'PLAYER_SHA256', hashlib.sha256(player_bytes).hexdigest())
    from obed_edom import html_preview as hp
    digest = hashlib.sha256(b'attach-mode-deck').hexdigest()
    export_key = hp.cache_key(digest)
    job = SimpleNamespace(id='prepared', kind='html-preview', status='done', result={
        'phase': 'ready', 'path': '/example/deck.key', 'exportKey': export_key,
        'sourceDigest': digest, 'manifest': {'playerDigest': live.PLAYER_SHA256},
        'slides': [],
    })
    runner = SimpleNamespace(get=lambda key: job if key == job.id else None, list=lambda **kwargs: [job])
    monkeypatch.setattr(live, 'registered_export_root', lambda *_: root)
    monkeypatch.setattr(live, 'file_sha256', lambda *_: live.PLAYER_SHA256)
    monkeypatch.setattr(live, 'load_header', lambda *_: ({'slideWidth': 1920, 'slideHeight': 1080, 'showMode': 0}, 'header.json'))
    service = LiveSessionService()

    def host_factory(export_root, slides, *, display_id=None):
        return LiveOutputHost(export_root, slides, transport_factory=FakeAttachCdp, server_factory=FakeAttachServer)

    app = FastAPI()
    app.include_router(live.live_router(runner, service=service, host_factory=host_factory, displays=lambda: []))
    client = TestClient(app, base_url='http://127.0.0.1')
    assert client.get('/api/live/displays').json() == []
    response = client.post('/api/live', json={'previewJobId': 'prepared'})
    state = response.json()
    assert response.status_code == 200, state
    assert state.get('error') is None, state
    assert state['output']['transport'] == 'fill-key', state
    assert state['output']['alpha'] is True
    assert 'displayId' not in state['output']
