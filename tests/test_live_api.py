import hashlib

from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import ANY

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
        self.reason = None
        self.setup = None
        self.calibration = object()

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
                'device': {'name': None, 'set': False}, 'keyer': self.keyer, 'setup': self.setup,
                'warnings': list(self.warnings), **({'reason': self.reason} if self.reason else {})}

    @property
    def setup_active(self):
        return self.setup is not None

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

    def check(self, reset_page=False):
        self._call('check', reset_page)

    def apply_settings(self, mode, rate, keyer):
        self._call('apply_settings', mode, rate, keyer)

    def show(self):
        self._call('show')

    def setup_device_begin(self, rate):
        self._call('setup_device_begin', rate)
        self._settle_setup(rate)

    def setup_device_done(self):
        self._call('setup_device_done')
        self._settle_setup(None)

    def _settle_setup(self, rate):
        self.status, self.reason, self.setup = ('blocked', 'deviceSetup', rate) if rate else ('stopped', None, None)

    def shutdown(self, timeout):
        self._call('shutdown', timeout)
        self.status = 'stopped'
        return True

    def calibration_adapter(self):
        return self.calibration

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
        self.placement = None
        self.recalibrate_calls = 0

    def capabilities(self):
        capabilities = {op: {'supported': True} for op in ('advance', 'goTo', 'hide', 'show')}
        if self.kwargs.get('bridge') == 'obs-managed' and self.kwargs.get('calibration') is not None:
            capabilities['recalibrate'] = (
                {'supported': False, 'reason': 'Calibration is already running.'}
                if self.placement and self.placement['state'] == 'probing'
                else {'supported': True}
            )
        else:
            capabilities['recalibrate'] = {
                'supported': False,
                'reason': 'Recalibration is available only for managed OBS output.',
            }
        return capabilities

    def observe(self):
        output = {**self.output, 'placement': self.placement} if self.placement else None
        return PlayerObservation(original_slide=1 + self.clicks, scene_id=str(self.clicks), output_visible=self.visible,
                                 output=output)

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
        elif operation == 'recalibrate':
            self.recalibrate_calls += 1
            self.placement = {
                'state': 'probing', 'grant': None, 'reason': 'calibrating', 'at': None,
                'product': 'Chrome/127.0.0.0', 'gpuCompositing': None, 'method': 'probe',
                'probeId': 'probe-1', 'leaseMs': None, 'leaseExpiresAt': None,
                'tone': {'observed': None, 'applied': 'identity'}, 'automaticProbesDisabled': False,
            }
        return self.observe()

    def stop(self):
        self.stopped = True
        if self.release:
            self.release.set()


OLD_PLAYER = 'e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354'
NEW_PLAYER = '17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91'


def client_for(tmp_path, monkeypatch, engine=None, events=None, player=OLD_PLAYER):
    thumb = tmp_path / 'thumbnail.jpeg'
    thumb.write_bytes(b'jpeg')
    job = SimpleNamespace(id='prepared', kind='html-preview', status='done', result={
        'phase': 'ready', 'path': '/example/deck.key', 'exportKey': 'key',
        'sourceDigest': 'source', 'manifest': {'playerDigest': player},
        'slides': [{'originalOrdinal': 1, 'playerIndex': 0, 'exportedUuid': 'uuid', 'skipped': False}],
    })
    runner = SimpleNamespace(get=lambda key: job if key == job.id else None,
                             list=lambda **kwargs: [job])
    monkeypatch.setattr(live, 'registered_export_root', lambda *_: tmp_path)
    monkeypatch.setattr(live, 'safe_export_file', lambda *_: thumb)
    monkeypatch.setattr(live, 'file_sha256', lambda *_: player)
    monkeypatch.setattr(live, 'load_header', lambda *_: ({'slideWidth': 1920, 'slideHeight': 1080, 'showMode': 0}, 'header.json'))
    monkeypatch.setattr(live, 'derive_runtime', lambda *args, **kwargs: (SimpleNamespace(refusals=()), {'movies': {}}))
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
    assert state['outputVisible']
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


def test_live_api_accepts_both_supported_players_and_refuses_others(tmp_path, monkeypatch):
    assert set(live.SUPPORTED_PLAYERS) == {OLD_PLAYER, NEW_PLAYER}
    client, claims, _, _, adapters, _ = client_for(tmp_path, monkeypatch, player=NEW_PLAYER)
    state = client.post('/api/live', json={'previewJobId': 'prepared', 'displayId': '42'}).json()
    assert state['sessionId'] and len(claims) == 1 and len(adapters) == 1
    client.post(f"/api/live/{state['sessionId']}/commands", json={'requestId': 'stop', 'operation': 'stop'})
    client, claims, _, _, adapters, _ = client_for(tmp_path, monkeypatch, player='0' * 64)
    response = client.post('/api/live', json={'previewJobId': 'prepared', 'displayId': '42'})
    assert response.status_code == 409
    assert 'This player version is not supported for live controls.' in response.text
    assert not claims and not adapters


@pytest.mark.parametrize(
    "command",
    [{'operation': 'goTo', 'slide': True}, {'operation': 'bogus'}],
    ids=['non-integer-go-to', 'unknown-operation'],
)
def test_live_api_rejects_malformed_command(tmp_path, monkeypatch, command):
    client, _, _, _, _adapters, _service = client_for(tmp_path, monkeypatch)
    state = client.post('/api/live', json={'previewJobId': 'prepared'}).json()
    session = state['sessionId']
    response = client.post(f'/api/live/{session}/commands', json={'requestId': 'x', **command})
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
    monkeypatch.delenv('OBED_LIVE_MM_OPACITY', raising=False)
    root = tmp_path / 'out' / '.html-preview' / 'export'
    (root / 'assets' / 'player').mkdir(parents=True)
    mm_anchors = b';'.join(before for before, _after in live_runtime._MM_OPACITY_REPLACEMENTS)
    player_bytes = b'before;' + live_runtime._ANCHOR + b';' + mm_anchors + b';after'
    (root / 'assets' / 'player' / 'main.js').write_bytes(player_bytes)
    (root / 'assets' / 'header.json').write_text('{"slideWidth":1920,"slideHeight":1080,"showMode":0}')
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player_bytes).hexdigest(), (ANY,) * 3)
    from obed_edom import html_preview as hp
    digest = hashlib.sha256(b'attach-mode-deck').hexdigest()
    export_key = hp.cache_key(digest)
    job = SimpleNamespace(id='prepared', kind='html-preview', status='done', result={
        'phase': 'ready', 'path': '/example/deck.key', 'exportKey': export_key,
        'sourceDigest': digest, 'manifest': {'playerDigest': OLD_PLAYER},
        'slides': [{'originalOrdinal': 1, 'playerIndex': 0, 'skipped': False}],
    })
    runner = SimpleNamespace(get=lambda key: job if key == job.id else None, list=lambda **kwargs: [job])
    monkeypatch.setattr(live, 'registered_export_root', lambda *_: root)
    monkeypatch.setattr(live, 'file_sha256', lambda *_: OLD_PLAYER)
    monkeypatch.setattr(live, 'load_header', lambda *_: ({'slideWidth': 1920, 'slideHeight': 1080, 'showMode': 0}, 'header.json'))
    monkeypatch.setattr(live, 'derive_runtime', lambda *args, **kwargs: (None, {}))
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
    served = live_runtime.patch_player(player_bytes, mm_opacity=True)
    assert state['output']['mmOpacity'] == {'mode': 'on', 'sha256': hashlib.sha256(served).hexdigest()}


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


ENGINE_STATE_KEYS = {'state', 'obs', 'rate', 'device', 'keyer', 'setup', 'warnings'}
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
    assert ENGINE_STATE_KEYS <= set(body) <= ENGINE_STATE_KEYS | {'reason'}
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


def test_engine_check_asks_for_a_page_reset_only_without_a_loaded_session(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    assert client.post('/api/live/engine/check').status_code == 200
    assert engine.calls[-1] == ('check', True)
    engine.status = 'ready'
    assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200
    assert client.post('/api/live/engine/check').status_code == 200
    assert engine.calls[-1] == ('check', False)
    assert engine.actions() == ['check', 'check']


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
    """The exact kwargs (no `gl_replay`, no `mm_opacity`) are the Keyer contract that `OBED_LIVE_GL_REPLAY` and
    `OBED_LIVE_MM_OPACITY` win over the host's defaults."""
    client, engine, adapters, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer', akOutputRate=30)
    engine.status = 'ready'
    response = client.post('/api/live', json={'previewJobId': 'prepared', 'displayId': '42'})
    assert response.status_code == 200, response.text
    assert adapters[-1].kwargs == {
        'display_id': None, 'continuity': 'auto', 'attach_endpoint': 'http://127.0.0.1:9333',
        'attach_match': 'TARGET-1', 'bridge': 'obs-managed', 'output_rate': 30,
        'calibration': engine.calibration,
    }
    assert response.json()['capabilities']['recalibrate'] == {'supported': True}
    assert engine.actions() == []


def test_managed_recalibrate_schedules_once_and_replays_without_navigation_or_visibility_ack(tmp_path, monkeypatch):
    client, engine, adapters, _ = engine_client(tmp_path, monkeypatch, akOutputMode='keyer')
    engine.status = 'ready'
    state = client.post('/api/live', json={'previewJobId': 'prepared'}).json()
    session = state['sessionId']
    command = {'requestId': 'cal-1', 'operation': 'recalibrate', 'slide': None}

    first = client.post(f'/api/live/{session}/commands', json=command).json()
    replay = client.post(f'/api/live/{session}/commands', json=command).json()
    concurrent = client.post(
        f'/api/live/{session}/commands', json={'requestId': 'cal-2', 'operation': 'recalibrate'},
    ).json()
    with_slide = client.post(
        f'/api/live/{session}/commands', json={'requestId': 'cal-3', 'operation': 'recalibrate', 'slide': 1},
    ).json()

    assert first == replay
    assert first['outcome'] == 'completed'
    assert first['state']['status'] == 'ready'
    assert first['state']['originalSlide'] == state['originalSlide']
    assert first['state']['outputVisible'] == state['outputVisible']
    assert first['state']['output']['placement']['state'] == 'probing'
    assert first['state']['output']['placement']['probeId'] == 'probe-1'
    assert concurrent['outcome'] == 'rejected'
    assert concurrent['reason'] == 'Calibration is already running.'
    assert with_slide['outcome'] == 'rejected'
    assert with_slide['reason'] == 'Only goTo accepts a slide number.'
    assert adapters[-1].recalibrate_calls == 1


def test_screen_start_passes_no_engine_kwargs(tmp_path, monkeypatch):
    client, engine, adapters, _ = engine_client(tmp_path, monkeypatch)
    engine.status = 'ready'
    assert client.post('/api/live', json={'previewJobId': 'prepared', 'displayId': '42'}).status_code == 200
    assert adapters[-1].kwargs == {'display_id': 42, 'continuity': 'auto'}
    state = client.get('/api/live').json()
    assert state['capabilities']['recalibrate'] == {
        'supported': False, 'reason': 'Recalibration is available only for managed OBS output.',
    }
    assert engine.actions() == []


def test_output_settings_put_saves_clamped_values_and_hands_them_to_the_engine(tmp_path, monkeypatch):
    client, engine, _, _ = engine_client(tmp_path, monkeypatch)
    response = client.put('/api/live/output-settings', json={'akOutputMode': 'keyer', 'akOutputRate': 60, 'akKeyer': 'off'})
    assert response.status_code == 200
    assert response.json() == {'akOutputMode': 'keyer', 'akOutputRate': 25, 'akKeyer': 'off'}
    stored = settings_mod.load_settings()
    assert (stored['akOutputMode'], stored['akOutputRate'], stored['akKeyer']) == ('keyer', 25, 'off')
    assert stored['reusePreviews'] is True
    assert client.put('/api/live/output-settings', json={'akOutputRate': 30}).json()['akOutputRate'] == 30
    assert client.put('/api/live/output-settings', json={'akOutputMode': 'screen'}).status_code == 200
    assert [call for call in engine.calls if call[0] != 'has_orphan'] == [
        ('apply_settings', 'keyer', 25, 'off'), ('apply_settings', 'keyer', 30, 'off'), ('apply_settings', 'screen', 30, 'off')]


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
        for settle in self.pending:
            settle()
        self.pending.clear()

    def _defer(self, published, settle):
        self.status = published
        self.pending.append(settle)

    def quit(self):
        self._call('quit')
        self._defer('quitting', lambda: setattr(self, 'status', 'stopped'))

    def restart(self, rate, keyer):
        self._call('restart', rate, keyer)
        self._defer('starting', lambda: setattr(self, 'status', 'ready'))

    def setup_device_begin(self, rate):
        self._call('setup_device_begin', rate)
        self._defer('starting', lambda: self._settle_setup(rate))

    def setup_device_done(self):
        self._call('setup_device_done')
        self._defer('quitting', lambda: self._settle_setup(None))

    def check(self, reset_page=False):
        self._call('check', reset_page)
        if reset_page:
            self._defer('starting', lambda: setattr(self, 'status', 'ready'))


@pytest.mark.parametrize(('action', 'pending'), [('quit', 'quitting'), ('restart', 'starting'), ('setupDevice', 'starting'), ('check', 'starting')])
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
    expected = 200 if action in ('restart', 'check') else 409
    assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == expected


def test_device_setup_settles_blocked_and_refuses_output_settings_until_done(tmp_path, monkeypatch):
    settings_mod.save_settings({**settings_mod.load_settings(), 'akOutputMode': 'keyer', 'akOutputRate': 30}, validate_dir=False)
    engine = DeferredEngine()
    client, _claims, _releases, _job, adapters, _service = client_for(tmp_path, monkeypatch, engine=engine)
    assert client.post('/api/live/engine/setupDevice').json()['state'] == 'starting'
    engine.run_pending()
    body = client.get('/api/live/engine').json()
    assert (body['state'], body['reason'], body['setup']) == ('blocked', 'deviceSetup', 30)
    response = client.put('/api/live/output-settings', json={'akOutputMode': 'screen'})
    assert response.status_code == 409
    assert response.json() == {'detail': 'Finish device setup first.'}
    assert settings_mod.load_settings()['akOutputMode'] == 'keyer'
    assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 409
    assert client.post('/api/live/engine/setupDone').json()['state'] == 'quitting'
    engine.run_pending()
    body = client.get('/api/live/engine').json()
    assert (body['state'], body['setup']) == ('stopped', None)
    assert 'reason' not in body
    assert client.put('/api/live/output-settings', json={'akOutputMode': 'screen'}).status_code == 200
    assert engine.actions() == ['setup_device_begin', 'setup_device_done', 'apply_settings']
    assert not adapters


def test_routes_only_use_engine_attributes_the_real_managed_obs_has():
    # The route tests run against FakeEngine, so a method the routes call but ManagedObs lacks would only
    # fail on a live dashboard. Parse every engine attribute web/live.py touches and check the real class.
    import re

    from obed_edom.managed_obs import ManagedObs

    source = (Path(__file__).resolve().parents[1] / "src/obed_edom/web/live.py").read_text()
    receivers = r'(?:\bmanaged|\bused_engine\(\)|\bengine\(\)|engine_slot\["engine"\])'
    used = set(re.findall(receivers + r"\.([A-Za-z_]+)", source))
    assert {"ensure_started", "shutdown", "apply_settings", "check", "setup_active", "target_id"} <= used
    missing = sorted(name for name in used if not hasattr(ManagedObs, name))
    assert missing == []
    import inspect

    assert "reset_page" in inspect.signature(ManagedObs.check).parameters
    assert list(inspect.signature(ManagedObs.apply_settings).parameters)[1:] == ["mode", "rate", "keyer"]


def test_deck_qualification_reports_continuity_and_conversions_without_starting_output(tmp_path, monkeypatch):
    client, claims, _, job, adapters, _ = client_for(tmp_path, monkeypatch)
    monkeypatch.delenv('OBED_LIVE_CONTINUITY', raising=False)
    refusal = {'fromPlayer': 0, 'toPlayer': 1, 'atScene': 2, 'asset': 'vid-20250608-wa0125.mp4', 'movieKey': 'm1',
               'objectId': 'instance-without-runtime-entry', 'code': 'R11', 'reason': 'R11: unmeasured export shape'}
    monkeypatch.setattr(live, 'derive_runtime', lambda *args, **kwargs: (SimpleNamespace(refusals=(refusal,)), {'movies': {}}))
    job.result['slides'].append({'originalOrdinal': 2, 'playerIndex': 1, 'skipped': False})
    converted = [
        {'path': f'assets/{folder}/assets/untitled.mov', 'asset': 'untitled.mov', 'sourceCodec': 'HEVC',
         'sourceSha256': 'a', 'sha256': 'b', 'bytes': 1}
        for folder in ('s1', 's2')
    ] + [
        {'path': f'assets/{folder}/assets/keyed.mov', 'asset': 'keyed.mov', 'sourceCodec': 'ProRes',
         'targetCodec': 'VP9 alpha', 'sourceSha256': 'c', 'sha256': 'd', 'bytes': 2}
        for folder in ('s1', 's2')
    ]
    job.result['manifest']['movieConversion'] = {'encoder': 'libx264 crf14 fast yuv420p; aac 192k', 'converted': converted}
    response = client.get('/api/live/decks/prepared/qualification')
    assert response.status_code == 200
    assert response.json() == {
        'previewJobId': 'prepared', 'name': 'deck.key', 'sourceDigest': 'source', 'slides': 2, 'qualified': True,
        'sourceState': 'missing', 'sourcePath': '/example/deck.key',
        'continuity': {'mode': 'qualified', 'reason': None, 'notCarried': [{
            'fromSlide': 1, 'toSlide': 2, 'asset': 'vid-20250608-wa0125.mp4', 'objectId': 'instance-without-runtime-entry',
            'code': 'R11', 'reason': 'R11: unmeasured export shape'}]},
        'convertedMovies': [
            {'asset': 'untitled.mov', 'sourceCodec': 'HEVC', 'targetCodec': 'H.264'},
            {'asset': 'keyed.mov', 'sourceCodec': 'ProRes', 'targetCodec': 'VP9 alpha'},
        ],
    }
    monkeypatch.setenv('OBED_LIVE_CONTINUITY', 'off')
    job.result['manifest']['movieConversion']['converted'] = []
    report = client.get('/api/live/decks/prepared/qualification').json()
    assert report['continuity'] == {'mode': 'off', 'reason': 'OBED_LIVE_CONTINUITY is off.', 'notCarried': []}
    assert report['convertedMovies'] == []
    assert not claims
    assert not adapters
    assert client.get('/api/live').json() is None


@pytest.mark.parametrize(
    ('case', 'expected_state'),
    [('current', 'current'), ('changed', 'changed'), ('missing', 'missing'),
     ('permission', 'missing'), ('symlink-loop', 'missing'), ('no-path', 'missing')],
)
def test_prepared_deck_source_state(tmp_path, monkeypatch, case, expected_state):
    source = tmp_path / f'{case}.key'
    if case in ('current', 'changed', 'permission'):
        source.write_bytes(b'original')
        source_digest = live.deck_digest(source)
    else:
        source_digest = 'source'
    if case == 'changed':
        source.write_bytes(b'edited source')
    elif case == 'permission':
        def denied(_path):
            raise PermissionError

        monkeypatch.setattr(live, 'deck_digest', denied)
    elif case == 'symlink-loop':
        source.symlink_to(source)

    client, _, _, job, _, _ = client_for(tmp_path, monkeypatch)
    job.result['sourceDigest'] = source_digest
    if case == 'no-path':
        job.result.pop('path')
        source_path = None
    else:
        job.result['path'] = str(source)
        source_path = str(source)

    deck = client.get('/api/live/decks').json()[0]
    qualification = client.get('/api/live/decks/prepared/qualification')
    assert qualification.status_code == 200
    report = qualification.json()
    assert report['qualified'] is True
    for payload in (deck, report):
        assert payload['sourceState'] == expected_state
        assert payload['sourcePath'] == source_path
    if case == 'changed':
        assert client.post('/api/live', json={'previewJobId': 'prepared'}).status_code == 200


@pytest.mark.parametrize('continuity', ['auto', 'off'])
def test_unsupported_continuity_is_reported_and_never_blocks_start(tmp_path, monkeypatch, continuity):
    client, claims, _, _, adapters, _ = client_for(tmp_path, monkeypatch)
    monkeypatch.delenv('OBED_LIVE_CONTINUITY', raising=False)
    monkeypatch.setattr(live, 'derive_runtime', lambda *args, **kwargs: live.Unsupported("R3: slide 2's transition is not on its last event"))
    report = client.get('/api/live/decks/prepared/qualification').json()
    assert report['qualified'] is True
    assert report['continuity'] == {'mode': 'unsupported', 'reason': "R3: slide 2's transition is not on its last event", 'notCarried': []}
    response = client.post('/api/live', json={'previewJobId': 'prepared', 'continuity': continuity})
    assert response.status_code == 200
    assert response.json()['outputVisible']
    assert [adapter.continuity for adapter in adapters] == [continuity]
    assert len(claims) == 1


@pytest.mark.parametrize('invalid', ['player', 'canvas', 'near-canvas', 'mode', 'media', 'slides'])
def test_qualification_uses_same_export_checks_as_start(tmp_path, monkeypatch, invalid):
    client, _, _, job, adapters, _ = client_for(tmp_path, monkeypatch)
    if invalid == 'player':
        job.result['manifest']['playerDigest'] = 'changed'
    elif invalid in ('canvas', 'mode'):
        header = {'slideWidth': 7680 if invalid == 'canvas' else 1920, 'slideHeight': 1080, 'showMode': 1 if invalid == 'mode' else 0}
        monkeypatch.setattr(live, 'load_header', lambda *_: (header, 'header.json'))
    elif invalid == 'near-canvas':
        # Within 0.001 of 16:9 but not exact; the host's export check refuses it.
        header = {'slideWidth': 1366, 'slideHeight': 768, 'showMode': 0}
        monkeypatch.setattr(live, 'load_header', lambda *_: (header, 'header.json'))
    elif invalid == 'media':
        job.result['slides'][0]['unsupportedMedia'] = ['remote video']
    else:
        job.result['slides'] = []
    report = client.get('/api/live/decks/prepared/qualification')
    start = client.post('/api/live', json={'previewJobId': 'prepared'})
    assert report.status_code == start.status_code == 409
    assert report.json()['detail'] == start.json()['detail']
    assert not adapters


@pytest.mark.parametrize(('gl_replay', 'family', 'status', 'expected'), [
    ('', 'h264', 200, {'mode': 'qualified', 'reason': None, 'notCarried': []}),
    ('sometimes', 'h264', 409, 'OBED_LIVE_GL_REPLAY must be off or auto.'),
    (None, 'vp9', 200, {'mode': 'unsupported', 'reason': 'movie continuity does not support VP9 movies: keyed.webm (vp09)',
                        'notCarried': []}),
])
def test_qualification_reports_the_continuity_the_host_loads(tmp_path, monkeypatch, gl_replay, family, status, expected):
    """A blank GL replay env falls back to the default and an invalid one refuses the load, as in the host;
    a carried movie the host cannot carry (here VP9 alpha) makes continuity unsupported rather than qualified."""
    client, _, _, _, _, _ = client_for(tmp_path, monkeypatch)
    monkeypatch.delenv('OBED_LIVE_CONTINUITY', raising=False)
    if gl_replay is None:
        monkeypatch.delenv('OBED_LIVE_GL_REPLAY', raising=False)
    else:
        monkeypatch.setenv('OBED_LIVE_GL_REPLAY', gl_replay)
    runtime = {'movies': {'m1': {'assetKeys': ['keyed.webm']}}}
    monkeypatch.setattr(live, 'derive_runtime', lambda *args, **kwargs: (SimpleNamespace(refusals=()), runtime))
    codec = 'vp09' if family == 'vp9' else 'avc1'
    monkeypatch.setattr(live, 'codec_report', lambda *args, **kwargs: [
        {'asset': 'keyed.webm', 'codec': codec, 'family': family, 'files': 1}], raising=False)
    response = client.get('/api/live/decks/prepared/qualification')
    assert response.status_code == status
    assert response.json().get('continuity', response.json().get('detail')) == expected


def test_keyer_qualification_uses_gl_plan_and_native_fallback(tmp_path, monkeypatch):
    client, _, _, _, _, _ = client_for(tmp_path, monkeypatch)
    settings_mod.save_settings({'akOutputMode': 'keyer'}, validate_dir=False)
    monkeypatch.delenv('OBED_LIVE_GL_REPLAY', raising=False)
    monkeypatch.delenv('OBED_LIVE_CONTINUITY', raising=False)
    calls = []

    def derive(*args, **kwargs):
        calls.append(kwargs.get('gl_replay', False))
        return live.Unsupported('no GL plan') if kwargs.get('gl_replay') else (SimpleNamespace(refusals=()), {'movies': {}})

    monkeypatch.setattr(live, 'derive_runtime', derive)
    assert client.get('/api/live/decks/prepared/qualification').json()['continuity']['mode'] == 'qualified'
    assert calls == [True, False]
