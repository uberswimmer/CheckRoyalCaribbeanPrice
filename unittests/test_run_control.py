"""Real local HTTP/process/lock tests. The child is a fixture, never the Royal checker."""
import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest
pytest.importorskip('fcntl', reason='Run control is an optional Linux Docker feature')
import run_control as rc


def wait_for(condition):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError('Timed out waiting for fixture process')


@pytest.fixture
def runner(tmp_path):
    script = tmp_path / 'fixture.py'
    script.write_text("""import os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / 'started').write_text(str(os.getpid()))
while not (root / 'finish').exists(): time.sleep(0.02)
sys.exit(int((root / 'finish').read_text()))
""")
    runner = rc.CheckRunner(tmp_path / 'control', (sys.executable, str(script), str(tmp_path)))
    yield runner, tmp_path
    runner.close()


@pytest.fixture
def api(runner):
    runner, root = runner
    server = rc.ControlServer(('127.0.0.1', 0), runner, 'http://reports.test:8088')
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02))
    thread.start()
    def fetch(method='GET', path='/api/check', headers=None, body=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        values = {'Host':server.host}
        if method == 'POST':
            values.update(Origin=server.origin, **{'X-CSRF-Token':server.token})
        values.update(headers or {})
        values = {k:v for k,v in values.items() if v is not None}
        connection.request(method, path, headers=values, body=body)
        response = connection.getresponse()
        content = response.read()
        result = (response.status, dict(response.headers),
                  json.loads(content) if response.getheader('Content-Type') == 'application/json' else content)
        connection.close()
        return result
    yield server, fetch, root
    server.shutdown(); thread.join(); server.server_close()


@pytest.mark.parametrize('exit_code', [0, 2])
def test_manual_run_reports_progress_completion_and_cooldown(api, exit_code):
    server, fetch, root = api
    status, headers, state = fetch()
    assert status == 200 and state['state'] == 'idle'
    assert headers['Cache-Control'] == 'no-store' and state['token'] == server.token
    assert fetch('POST')[0] == 202
    wait_for(lambda: (root / 'started').exists())
    running = fetch()[2]
    assert running['state'] == 'running' and running['runId']
    assert fetch('POST')[0] == 409
    (root / 'finish').write_text(str(exit_code))
    wait_for(lambda: fetch()[2]['state'] != 'running')
    done = fetch()[2]
    assert done['state'] == ('completed' if exit_code == 0 else 'failed')
    assert done['runId'] == running['runId'] and done['exitCode'] == exit_code
    assert fetch('POST')[0] == 429
    assert set(p.name for p in (root / 'control').iterdir()) == {'check.lock','status.lock','status.json'}
    assert (root / 'control/status.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('headers', [
    {'Host':'attacker.test:8088'}, {'Origin':None}, {'Origin':'http://attacker.test'},
    {'Origin':'null'}, {'X-CSRF-Token':None}, {'X-CSRF-Token':'invalid'},
    {'X-CSRF-Token':'é'}, {'Sec-Fetch-Site':'cross-site'}, {'Sec-Fetch-Site':'same-site'},
])
def test_untrusted_browser_requests_never_start_a_check(api, headers):
    _, fetch, root = api
    assert fetch('POST', headers=headers)[0] == 403
    assert not (root / 'started').exists() and not (root / 'control/status.json').exists()


@pytest.mark.parametrize('path, body, expected', [
    ('/api/check?command=anything',None,404), ('/api/check/other',None,404),
    ('/api/check','{"command":"anything"}',400), ('/api/check','x',400),
])
def test_arguments_and_request_bodies_are_rejected(api, path, body, expected):
    _, fetch, root = api
    assert fetch('POST',path=path,body=body)[0] == expected
    assert not (root / 'started').exists()


def test_cross_origin_status_and_preflight_are_rejected(api):
    _, fetch, root = api
    assert fetch(headers={'Origin':'http://attacker.test'})[0] == 403
    assert fetch('OPTIONS',headers={'Origin':'http://attacker.test'})[0] == 501
    assert fetch('PUT')[0] == 501
    assert not (root / 'started').exists()


def test_duplicate_security_headers_are_rejected(api):
    server, _, root = api
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    connection.putrequest('POST', '/api/check', skip_host=True)
    for key, value in [('Host',server.host),('Origin',server.origin),('Origin',server.origin),
                       ('X-CSRF-Token',server.token),('Content-Length','0')]:
        connection.putheader(key,value)
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 403
    response.read(); connection.close()
    assert not (root / 'started').exists()


def test_web_and_scheduled_writers_share_lock_and_existing_status(api):
    server, fetch, root = api
    scheduled = rc.CheckRunner(server.runner.directory, server.runner.command)
    fd, state = scheduled.reserve()
    try:
        assert fetch()[2]['state'] == 'running'
        assert fetch('POST')[0] == 409
        assert scheduled.read_state()['runId'] == state['runId']
    finally:
        os.close(fd)
    assert fetch()[2]['state'] == 'interrupted'
    state['startedEpoch'] -= 61
    scheduled.write_state(state)
    assert fetch('POST')[0] == 202
    with pytest.raises(rc.RunUnavailable): scheduled.reserve()


def test_shutdown_stops_child_and_releases_lock(runner):
    runner, root = runner
    runner.start()
    wait_for(lambda: (root / 'started').exists())
    runner.close()
    assert runner.snapshot()['state'] == 'failed'
    assert not runner.worker.is_alive()


def test_status_poll_cannot_make_a_scheduled_check_skip(runner, monkeypatch):
    runner, root = runner
    inspecting = threading.Event()
    release = threading.Event()
    original = runner.read_state
    def slow_read():
        inspecting.set()
        assert release.wait(3)
        return original()
    monkeypatch.setattr(runner, 'read_state', slow_read)
    poll = threading.Thread(target=runner.snapshot)
    poll.start()
    assert inspecting.wait(3)
    admitted = []
    scheduled = rc.CheckRunner(runner.directory, runner.command)
    start = threading.Thread(target=lambda: admitted.append(scheduled.reserve()))
    start.start()
    release.set()
    poll.join(timeout=3); start.join(timeout=3)
    assert len(admitted) == 1
    os.close(admitted[0][0])


def test_failed_spawn_and_corrupt_status_fail_safely(api):
    server, fetch, root = api
    server.runner.command = ('/no-such-checker',)
    assert fetch('POST')[0] == 202
    wait_for(lambda: fetch()[2]['state'] == 'failed')
    (root / 'control/status.json').write_text('bad json')
    assert fetch()[0] == 503 and fetch('POST')[0] == 503


def test_killed_wrapper_keeps_child_lock_until_checker_exits(runner):
    runner, root = runner
    command = ('import run_control as r; '
               f'x=r.CheckRunner({str(runner.directory)!r}, {runner.command!r}); '
               'fd,state=x.reserve();x.execute(fd,state)')
    wrapper = subprocess.Popen([sys.executable, '-c', command], cwd=Path(rc.__file__).parent)
    child = None
    try:
        wait_for(lambda: (root / 'started').exists())
        child = int((root / 'started').read_text())
        wrapper.kill(); wrapper.wait(timeout=3)
        with pytest.raises(rc.RunUnavailable): runner.reserve()
        assert runner.snapshot()['state'] == 'running'
        os.killpg(child, signal.SIGTERM)
        wait_for(lambda: runner.snapshot()['state'] == 'interrupted')
    finally:
        if wrapper.poll() is None: wrapper.kill(); wrapper.wait(timeout=3)
        if child:
            try: os.killpg(child,signal.SIGKILL)
            except ProcessLookupError: pass


@pytest.mark.parametrize('origin', ['', 'reports.test', 'http://user:pass@reports.test',
                                   'http://reports.test/path', 'http://reports.test?arg=1'])
def test_control_requires_a_single_explicit_origin(tmp_path, origin):
    with pytest.raises(ValueError):
        rc.ControlServer(('127.0.0.1',0), rc.CheckRunner(tmp_path), origin)


def test_default_port_normalizes_to_browser_origin(tmp_path):
    server = rc.ControlServer(('127.0.0.1',0),rc.CheckRunner(tmp_path),'http://reports.test:80/')
    assert server.origin == 'http://reports.test' and server.host == 'reports.test'
    server.server_close()
