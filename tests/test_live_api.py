import hashlib
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from obed_edom import live_runtime
from obed_edom import settings as settings_mod
from obed_edom.live_host import LiveOutputHost, OutputDisplay
from obed_edom.live_session import LiveSessionService, PlayerObservation
from obed_edom.web import live


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, 'settings_path', lambda root=None: tmp_path / 'settings.json')


class FakeEngine:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.calls = []
        self.status = 'stopped'
        self.warnings = []
        self.orphan = False
        self.rate, self.keyer = 25, 'external'

    def _call(self, *call):
        self.calls.append(call)
        self.events.append(('engine',) + call)

    @property
    def cdp_endpoint(self):
        return 'http://127.0.0.1:9333' if self.status in ('starting', 'ready', 'blocked') else None

    @property
    def target_id(self):
        return 'TARGET-1' if self.status == 'ready' else None

    def state(self):
        return {'state': self.status, 'obs': {'path': '/Applications/OBS.app', 'version': '32.2.2', 'pinned': '32.2.2'},
                'rate': {'output': self.rate, 'canvas': '25 PAL', 'source': 50},
                'device': {'name': None, 'set': False}, 'keyer': self.keyer, 'warnings': list(self.warnings)}

    def configure(self, rate, keyer):
        self.rate, self.keyer = rate, keyer
        self._call('configure', rate, keyer)

    def has_orphan(self):
        self._call('has_orphan')
        return self.orphan

    def ensure_started(self, rate, keyer):
        self._call('ensure_started', rate, keyer)
        self.status = 'ready'

    def restart(self, rate, keyer):
        self._call('restart', rate, keyer)
        self.status, self.warnings = 'ready', []

    def quit(self):
        self._call('quit')
        self.status = 'stopped'

    def check(self):
        self._call('check')

    def show(self):
        self._call('show')

    def reset_page(self):
        self._call('reset_page')

    def setup_device_begin(self, rate):
        self._call('setup_device_begin', rate)

    def setup_device_done(self):
        self._call('setup_device_done')

    @property
    def active(self):
        return self.status != 'stopped'

    def shutdown(self, timeout):
        self._call('shutdown', timeout)
        self.status = 'stopped'
        return True

    def actions(self):
        return [call[0] for call in self.calls if call[0] not in ('configure', 'has_orphan')]


class Adapter:
    output = {'width': 1920, 'height': 1080}

    def __init__(self, *args, **kwargs):
        self.continuity = kwargs.get("continuity", "auto")
        self.kwargs = kwargs
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


def client_for(tmp_path, monkeypatch, engine=None, events=None):
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
    events = events if events is not None else []

    def release(*args):
        releases.append(args)
        events.append(('release',) + args)

    service = LiveSessionService(claim=lambda *args: claims.append(args), release=release)
    adapters = []
    engine = engine or FakeEngine(events)

    def host_factory(*args, **kwargs):
        adapter = Adapter(*args, **kwargs)
        adapters.append(adapter)
        return adapter

    app = FastAPI()
    app.include_router(live.live_router(runner, service=service, host_factory=host_factory,
        displays=lambda: [OutputDisplay(42, 1920, 0, 2560, 1440, False)], engine_factory=lambda: engine))
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

    def host_factory(export_root, slides, *, display_id=None, continuity="auto"):
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


def test_live_start_forwards_per_session_continuity_opt_out(tmp_path, monkeypatch):
    client, _, _, _, adapters, _ = client_for(tmp_path, monkeypatch)
    response = client.post('/api/live', json={'previewJobId': 'prepared', 'continuity': 'off'})
    assert response.status_code == 200
    assert adapters[-1].continuity == 'off'


def test_live_start_rejects_unknown_continuity_mode(tmp_path, monkeypatch):
    client, _, _, _, adapters, _ = client_for(tmp_path, monkeypatch)
    response = client.post('/api/live', json={'previewJobId': 'prepared', 'continuity': 'force'})
    assert response.status_code == 422
    assert not adapters


def test_live_api_snapshot_surfaces_auto_play_deferred_and_advance_clears_it(tmp_path, monkeypatch):
    client, _, _, _, adapters, _service = client_for(tmp_path, monkeypatch)
    state = client.post('/api/live', json={'previewJobId': 'prepared'}).json()
    assert state['autoPlayDeferred'] is None
    session = state['sessionId']
    adapter = adapters[-1]

    def goto_with_deferral(operation, slide=None):
        observed = Adapter.observe(adapter)
        return PlayerObservation(
            original_slide=observed.original_slide, scene_id=observed.scene_id,
            output_visible=observed.output_visible, auto_play_deferred='Movies idle until next advance',
        )

    adapter.execute = goto_with_deferral
    result = client.post(f'/api/live/{session}/commands', json={'requestId': 'g', 'operation': 'goTo', 'slide': 1}).json()
    assert result['state']['autoPlayDeferred'] == 'Movies idle until next advance'
    assert client.get('/api/live').json()['autoPlayDeferred'] == 'Movies idle until next advance'

    advanced = client.post(f'/api/live/{session}/commands', json={'requestId': 'a', 'operation': 'advance'}).json()
    assert advanced['state']['autoPlayDeferred'] is None


ENGINE_STATE_KEYS = {'state', 'obs', 'rate', 'device', 'keyer', 'warnings'}
W5 = {'id': 'obsExited', 'severity': 'block', 'action': 'restart',
      'text': 'OBS stopped unexpectedly — nothing is going to the keyer. Press Restart output engine.'}


def engine_client(tmp_path, monkeypatch, **settings):
    events = []
    engine = FakeEngine(events)
    if settings:
        settings_mod.save_settings({**settings_mod.load_settings(), **settings}, validate_dir=False)
    client, _claims, _releases, _job, adapters, _service = client_for(tmp_path, monkeypatch, engine=engine, events=events)
    return client, engine, adapters, events


def test_engine_get_configures_from_settings_and_never_starts(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer', akOutputRate=30, akKeyer='off')
    with client:
        body = client.get('/api/live/engine').json()
        assert client.get('/api/live/output-settings').json() == {'akOutputMode': 'keyer', 'akOutputRate': 30, 'akKeyer': 'off'}
        client.get('/api/live')
    assert body['state'] == 'stopped'
    assert body['rate']['output'] == 30 and body['keyer'] == 'off'
    assert ('configure', 30, 'off') in engine.calls
    assert engine.actions() == []


def test_engine_state_json_never_carries_a_password(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch)
    engine.status = 'ready'
    body = client.get('/api/live/engine').json()
    assert set(body) <= ENGINE_STATE_KEYS | {'reason', 'setup'}
    assert 'password' not in client.get('/api/live/engine').text.lower()


def test_engine_actions_dispatch_with_settings_rate_and_keyer(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer', akOutputRate=30, akKeyer='off')
    for action in ('start', 'restart', 'show', 'quit', 'setupDevice', 'setupDone'):
        response = client.post(f'/api/live/engine/{action}')
        assert response.status_code == 200, (action, response.text)
        assert set(response.json()) >= ENGINE_STATE_KEYS
    assert [call for call in engine.calls if call[0] != 'configure'] == [
        ('ensure_started', 30, 'off'), ('restart', 30, 'off'), ('show',), ('quit',),
        ('setup_device_begin', 30), ('setup_device_done',)]
    assert client.post('/api/live/engine/bogus').status_code == 422


def test_engine_check_resets_the_page_only_when_ready_and_idle(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    assert client.post('/api/live/engine/check').status_code == 200
    assert engine.actions() == ['check']
    engine.status = 'ready'
    client.post('/api/live/engine/check')
    assert engine.actions() == ['check', 'check', 'reset_page']
    assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200
    assert client.post('/api/live/engine/check').status_code == 200
    assert engine.actions() == ['check', 'check', 'reset_page', 'check']


def test_engine_changes_are_refused_while_a_session_is_loaded(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    engine.status = 'ready'
    assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200
    for action in ('start', 'restart', 'quit', 'setupDevice', 'setupDone'):
        response = client.post(f'/api/live/engine/{action}')
        assert response.status_code == 409, action
        assert response.json() == {'detail': 'Stop the show first.'}
    response = client.put('/api/live/output-settings', json={'akOutputRate': 30})
    assert response.status_code == 409
    assert response.json() == {'detail': 'Stop the show first.'}
    assert settings_mod.load_settings()['akOutputRate'] == 25
    engine.warnings = [{'id': 'obsWaiting', 'severity': 'block', 'text': 'waiting'}]
    assert client.post('/api/live/engine/restart').status_code == 409
    assert client.post('/api/live/engine/show').status_code == 200
    assert engine.actions() == ['show']
    assert client.get('/api/live').json()['status'] != 'stopped'


@pytest.mark.parametrize('warning_id', ['obsExited', 'obsPageLost', 'engineError', 'obsUnreachable'])
def test_restart_after_dead_output_stops_the_dead_session_first(tmp_path, monkeypatch, warning_id):
    client, engine, adapters, events = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    engine.status = 'ready'
    session = client.post('/api/live', json={'previewJobId': 'prepared'}).json()['sessionId']
    engine.status, engine.warnings = 'blocked', [{**W5, 'id': warning_id}]
    assert client.post('/api/live/engine/quit').status_code == 409
    response = client.post('/api/live/engine/restart')
    assert response.status_code == 200
    assert adapters[-1].stopped
    assert client.get('/api/live').json()['status'] == 'stopped'
    order = [event[0] if event[0] == 'release' else event[1] for event in events]
    assert order.index('release') < order.index('restart')
    assert any(event[0] == 'release' and event[2] == session for event in events)


def test_keyer_start_requires_a_ready_engine(tmp_path, monkeypatch):
    client, engine, adapters, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    response = client.post('/api/live', json={'previewJobId': 'prepared'})
    assert response.status_code == 409
    assert response.json()['detail'] == 'The output engine is not ready. Press Take output.'
    engine.status = 'blocked'
    engine.warnings = [{'id': 'noDevice', 'severity': 'warn', 'text': 'warn first'}, W5]
    response = client.post('/api/live', json={'previewJobId': 'prepared'})
    assert response.status_code == 409
    assert response.json()['detail'] == W5['text']
    assert not adapters
    assert engine.actions() == []


def test_keyer_start_attaches_to_the_engine_target_and_ignores_display(tmp_path, monkeypatch):
    client, engine, adapters, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer', akOutputRate=30)
    engine.status = 'ready'
    response = client.post('/api/live', json={'previewJobId': 'prepared', 'displayId': '42'})
    assert response.status_code == 200, response.text
    assert adapters[-1].kwargs == {
        'display_id': None, 'continuity': 'auto', 'attach_endpoint': 'http://127.0.0.1:9333',
        'attach_match': 'TARGET-1', 'bridge': 'obs-managed', 'output_rate': 30,
    }
    assert engine.actions() == []


def test_screen_start_passes_no_engine_kwargs(tmp_path, monkeypatch):
    client, engine, adapters, _ = engine_client(tmp_path, monkeypatch)
    engine.status = 'ready'
    assert client.post('/api/live', json={'previewJobId': 'prepared', 'displayId': '42'}).status_code == 200
    assert adapters[-1].kwargs == {'display_id': 42, 'continuity': 'auto'}
    assert engine.actions() == []


def test_output_settings_put_clamps_saves_and_configures(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch)
    response = client.put('/api/live/output-settings', json={'akOutputMode': 'keyer', 'akOutputRate': 60, 'akKeyer': 'off'})
    assert response.status_code == 200
    assert response.json() == {'akOutputMode': 'keyer', 'akOutputRate': 25, 'akKeyer': 'off'}
    stored = settings_mod.load_settings()
    assert (stored['akOutputMode'], stored['akOutputRate'], stored['akKeyer']) == ('keyer', 25, 'off')
    assert stored['reusePreviews'] is True
    assert ('configure', 25, 'off') in engine.calls
    assert engine.actions() == []


def test_output_settings_put_restarts_a_running_engine_only_on_rate_or_keyer_change(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    engine.status = 'ready'
    client.put('/api/live/output-settings', json={'akOutputMode': 'keyer'})
    assert engine.actions() == []
    client.put('/api/live/output-settings', json={'akOutputRate': 30})
    assert engine.calls[-1] == ('restart', 30, 'external')
    client.put('/api/live/output-settings', json={'akKeyer': 'off'})
    assert engine.calls[-1] == ('restart', 30, 'off')
    engine.status = 'stopped'
    client.put('/api/live/output-settings', json={'akOutputRate': 25})
    assert engine.actions() == ['restart', 'restart']


def test_output_settings_switch_to_screen_releases_a_running_engine(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    client.put('/api/live/output-settings', json={'akOutputMode': 'screen'})
    assert engine.actions() == []
    client.put('/api/live/output-settings', json={'akOutputMode': 'keyer'})
    engine.status = 'ready'
    client.put('/api/live/output-settings', json={'akOutputMode': 'screen', 'akOutputRate': 30})
    assert engine.actions() == ['quit']


def test_startup_checks_the_engine_only_when_an_orphan_exists(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch)
    with client:
        assert engine.calls == [('has_orphan',)]
    assert engine.actions() == []
    engine = FakeEngine()
    engine.orphan = True
    client, *_ = client_for(tmp_path, monkeypatch, engine=engine)
    with client:
        assert engine.actions() == ['check']
    assert engine.actions() == ['check', 'shutdown']
    assert engine.calls[-1] == ('shutdown', 35)


def test_shutdown_stops_the_session_before_releasing_the_engine(tmp_path, monkeypatch):
    client, engine, adapters, events = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    with client:
        assert client.post('/api/live/engine/start').status_code == 200
        assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200
    assert adapters[-1].stopped
    tail = [event[0] if event[0] == 'release' else event[1] for event in events][-2:]
    assert tail == ['release', 'shutdown']
    assert engine.calls[-1] == ('shutdown', 35)
    assert 'quit' not in engine.actions()


def test_shutdown_leaves_an_unused_engine_alone(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch)
    with client:
        client.get('/api/live/engine')
    assert engine.actions() == []


class DeferredEngine(FakeEngine):
    """Publishes the pending state synchronously; the work runs only when `run_pending` is called."""

    def __init__(self, events=None):
        super().__init__(events)
        self.pending = []

    def run_pending(self):
        for status in self.pending:
            self.status = status
        self.pending.clear()

    def quit(self):
        self._call('quit')
        self.status = 'quitting'
        self.pending.append('stopped')

    def restart(self, rate, keyer):
        self._call('restart', rate, keyer)
        self.status = 'starting'
        self.pending.append('ready')

    def setup_device_begin(self, rate):
        self._call('setup_device_begin', rate)
        self.status = 'quitting'
        self.pending.append('ready')


@pytest.mark.parametrize(('action', 'pending'), [('quit', 'quitting'), ('restart', 'starting'), ('setupDevice', 'quitting')])
def test_keyer_start_is_refused_while_an_engine_action_is_pending(tmp_path, monkeypatch, action, pending):
    settings_mod.save_settings({**settings_mod.load_settings(), 'akOutputMode': 'keyer'}, validate_dir=False)
    engine = DeferredEngine()
    engine.status = 'ready'
    client, _claims, _releases, _job, adapters, _service = client_for(tmp_path, monkeypatch, engine=engine)
    assert client.post(f'/api/live/engine/{action}').json()['state'] == pending
    response = client.post('/api/live', json={'previewJobId': 'prepared'})
    assert response.status_code == 409
    assert response.json()['detail'] == 'The output engine is not ready. Press Take output.'
    assert not adapters
    engine.run_pending()
    expected = 409 if action == 'quit' else 200
    assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == expected


def test_output_settings_put_uses_engine_activity_not_the_cdp_endpoint(tmp_path, monkeypatch):
    settings_mod.save_settings({**settings_mod.load_settings(), 'akOutputMode': 'keyer'}, validate_dir=False)
    engine = DeferredEngine()
    engine.status = 'ready'
    client, *_ = client_for(tmp_path, monkeypatch, engine=engine)
    client.post('/api/live/engine/setupDevice')
    assert engine.cdp_endpoint is None
    client.put('/api/live/output-settings', json={'akOutputMode': 'screen'})
    assert engine.actions() == ['setup_device_begin', 'quit']


def test_routes_only_use_engine_attributes_the_real_managed_obs_has():
    # The route tests run against FakeEngine, so a method the routes call but ManagedObs lacks would only
    # fail on a live dashboard. Parse every engine attribute web/live.py touches and check the real class.
    import re

    from obed_edom.managed_obs import ManagedObs

    source = (Path(__file__).resolve().parents[1] / "src/obed_edom/web/live.py").read_text()
    receivers = r'(?:\bmanaged|\bused_engine\(\)|\bengine\(\)|engine_slot\["engine"\])'
    used = set(re.findall(receivers + r"\.([A-Za-z_]+)", source))
    assert {"ensure_started", "shutdown", "active", "target_id"} <= used
    missing = sorted(name for name in used if not hasattr(ManagedObs, name))
    assert missing == []
