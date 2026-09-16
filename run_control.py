"""Optional Docker run control. No Royal credentials, shell commands, or API logic.

The checker, cron and web runs share an OS lock. Only the latest run's small status
record is saved, outside the public report directory. Direct Python use is unchanged.
"""
import fcntl
import json
import math
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit


CHECK_COMMAND = (sys.executable, str(Path(__file__).with_name('CheckRoyalCaribbeanPrice.py')))
CONTROL_DIRECTORY = Path('/app/data/run-control')
COOLDOWN_SECONDS = 60


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class RunUnavailable(Exception):
    def __init__(self, status, retry_after=0):
        self.status = status
        self.retry_after = retry_after


class CheckRunner:
    def __init__(self, directory=CONTROL_DIRECTORY, command=CHECK_COMMAND):
        self.directory = Path(directory)
        self.command = tuple(command)
        self.process_mutex = threading.Lock()
        self.child = None
        self.worker = None
        self.stopping = False

    @contextmanager
    def status_guard(self):
        # Serialize brief lock probes with admission. Otherwise a status poll
        # could briefly hold check.lock and make cron skip a legitimate run.
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.directory / 'status.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            yield

    def lock(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.directory / 'check.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        except BaseException:
            os.close(fd)
            raise
        return fd

    def read_state(self):
        try:
            data = json.loads((self.directory / 'status.json').read_text())
            if (not isinstance(data, dict) or data.get('state') not in ('running', 'completed', 'failed')
                    or not isinstance(data.get('runId'), str)
                    or type(data.get('startedEpoch')) not in (int, float)
                    or not math.isfinite(data['startedEpoch'])):
                raise ValueError('invalid status')
            return data
        except FileNotFoundError:
            return {'runId': None, 'state': 'idle', 'startedAt': None,
                    'finishedAt': None, 'exitCode': None, 'startedEpoch': 0}
        except (ValueError, TypeError):
            raise OSError('Cannot read check status') from None

    def write_state(self, state):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / 'status.json')
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def retry_after(state):
        return max(0, math.ceil(COOLDOWN_SECONDS - (time.time() - state['startedEpoch'])))

    def snapshot(self):
        with self.status_guard():
            fd = self.lock()
            try:
                state = self.read_state()
                if fd is None:
                    state['state'] = 'running'
                elif state['state'] == 'running':
                    state['state'] = 'interrupted'
                return {k: state.get(k) for k in ('runId', 'state', 'startedAt', 'finishedAt', 'exitCode')} | {
                    'retryAfter': self.retry_after(state)}
            finally:
                if fd is not None:
                    os.close(fd)

    def reserve(self, manual=False):
        with self.status_guard():
            fd = self.lock()
            if fd is None:
                raise RunUnavailable(409)
            try:
                previous = self.read_state()
                retry = self.retry_after(previous)
                if manual and retry:
                    raise RunUnavailable(429, retry)
                state = {'runId': secrets.token_hex(12), 'state': 'running',
                         'startedAt': timestamp(), 'finishedAt': None, 'exitCode': None,
                         'startedEpoch': time.time()}
                self.write_state(state)
                return fd, state
            except BaseException:
                os.close(fd)
                raise

    @staticmethod
    def stop_process(child):
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()

    def execute(self, fd, state, arguments=()):
        code = 1
        child = None
        try:
            with self.process_mutex:
                if self.stopping:
                    return 1
                # The child inherits the locked descriptor, so killing this wrapper
                # cannot permit another writer while the checker is still alive.
                child = self.child = subprocess.Popen(self.command + tuple(arguments),
                    stdin=subprocess.DEVNULL, pass_fds=(fd,), start_new_session=True)
            print('[Run control] Check started', flush=True)
            code = child.wait()
            return code
        except OSError:
            print('[Run control] Could not start checker', file=sys.stderr, flush=True)
            return 1
        finally:
            try:
                self.stop_process(child)
                with self.process_mutex:
                    self.child = None
                state.update(state='completed' if code == 0 else 'failed',
                             finishedAt=timestamp(), exitCode=code)
                self.write_state(state)
                print('[Run control] Check completed' if code == 0 else '[Run control] Check failed', flush=True)
            finally:
                os.close(fd)

    def start(self):
        fd, state = self.reserve(manual=True)
        self.worker = threading.Thread(target=self.execute, args=(fd, state), daemon=True)
        try:
            self.worker.start()
        except BaseException:
            os.close(fd)
            raise
        return state['runId']

    def close(self):
        with self.process_mutex:
            self.stopping = True
            child = self.child
        self.stop_process(child)
        if self.worker is not None:
            self.worker.join(timeout=10)


class ControlServer(HTTPServer):
    def __init__(self, address, runner, origin):
        parsed = urlsplit(origin)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError('CHECKER_WEB_ORIGIN must be the report page origin, such as http://192.0.2.10:8088')
        host = parsed.netloc.lower()
        if parsed.port == (80 if parsed.scheme == 'http' else 443):
            host = host.rsplit(':', 1)[0]
        self.origin = f'{parsed.scheme}://{host}'
        self.host = host
        self.token = secrets.token_urlsafe(32)
        self.runner = runner
        super().__init__(address, ControlHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class ControlHandler(BaseHTTPRequestHandler):
    server_version = 'CruiseCheck'
    sys_version = ''

    def log_message(self, *args):
        pass  # Status polling must not fill container logs.

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, write=False):
        if self.path != '/api/check':
            self.reply(404, {'error': 'Not found'})
            return False
        host = self.headers.get_all('Host', [])
        origin = self.headers.get_all('Origin', [])
        site = self.headers.get_all('Sec-Fetch-Site', [])
        if (len(host) != 1 or host[0].lower() != self.server.host
                or origin not in ([], [self.server.origin])
                or site not in ([], ['same-origin'], ['none'])):
            self.reply(403, {'error': 'Forbidden'})
            return False
        if write:
            tokens = self.headers.get_all('X-CSRF-Token', [])
            if (origin != [self.server.origin] or len(tokens) != 1
                    or not tokens[0].isascii()
                    or not secrets.compare_digest(tokens[0], self.server.token)):
                self.reply(403, {'error': 'Forbidden'})
                return False
            if (self.headers.get_all('Content-Length', []) != ['0']
                    or self.headers.get_all('Transfer-Encoding', [])):
                self.reply(400, {'error': 'Run requests must have an empty body'})
                return False
        return True

    def do_GET(self):
        if self.allowed():
            try:
                self.reply(200, self.server.runner.snapshot() | {'token': self.server.token})
            except OSError:
                self.reply(503, {'error': 'Check status unavailable; see container logs'})

    def do_POST(self):
        if not self.allowed(write=True):
            return
        try:
            run_id = self.server.runner.start()
            self.reply(202, {'runId': run_id, 'state': 'running'})
        except RunUnavailable as exc:
            self.reply(exc.status, {'error': 'Check already running' if exc.status == 409 else 'Please wait before another check',
                                    'retryAfter': exc.retry_after})
        except (OSError, RuntimeError):
            self.reply(503, {'error': 'Cannot start check; see container logs'})


def serve():
    runner = CheckRunner()
    server = ControlServer(('0.0.0.0', 8081), runner, os.environ.get('CHECKER_WEB_ORIGIN', ''))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    cron = None
    try:
        cron = subprocess.Popen(['crond', '-f', '-d', '8'], start_new_session=True)
        thread.start()
        print('[Run control] Manual checks enabled on internal port 8081', flush=True)
        while not stop.wait(1):
            if cron.poll() is not None or not thread.is_alive():
                raise RuntimeError('Scheduler or run-control server stopped')
    finally:
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        try:
            runner.close()
        finally:
            CheckRunner.stop_process(cron)


def main():
    if sys.argv[1:] == ['serve']:
        serve()
        return 0
    if len(sys.argv) < 2 or sys.argv[1] != 'check':
        raise ValueError('Usage: run_control.py check [checker arguments] | serve')
    arguments = tuple(sys.argv[2:])
    if any(arg in arguments for arg in ('--validate-config', '--help', '-h')):
        os.execv(CHECK_COMMAND[0], CHECK_COMMAND + arguments)
    runner = CheckRunner()
    def interrupt(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupt)
    try:
        fd, state = runner.reserve()
        return runner.execute(fd, state, arguments)
    except RunUnavailable:
        print('[Run control] A check is already running; this invocation was skipped', flush=True)
        return 75


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'[Run control] {error}', file=sys.stderr)
        sys.exit(1)
