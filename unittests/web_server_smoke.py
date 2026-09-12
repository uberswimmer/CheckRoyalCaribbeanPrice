"""Exercise the real static server in CI: python unittests/web_server_smoke.py URL EXPORT_DIR."""
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

base, directory = sys.argv[1], Path(sys.argv[2])


def fetch(path, method='GET', headers=None):
    try:
        response = urlopen(Request(base + path, method=method, headers=headers or {}), timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


for attempt in range(20):
    try:
        assert fetch('/')[0] == 503  # Nothing generated yet; no directory listing.
        break
    except URLError:
        time.sleep(0.25)
else:
    raise AssertionError('Report server did not start')

# Import after readiness; runner has the checker dependencies, web container does not.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import logging
import CheckRoyalCaribbeanPrice as c
report = c.WebReport(str(directory))
report.emit(logging.LogRecord('sample', logging.INFO, '', 0, c.BLUE + 'Example report' + c.RESET, (), None))
report.publish('Completed', finished=True)
c.calendar_atomic_write(directory / 'cruises.ics', b'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n', mode=0o644)
(directory / 'calendar-data.json').write_text('MUST NOT BE SERVED')
(directory / 'config.yaml').write_text('MUST NOT BE SERVED')
for path, mime, marker in [('/', 'text/html', b'Example report'),
                            ('/report.txt', 'text/plain', b'Example report'),
                            ('/cruises.ics', 'text/calendar', b'BEGIN:VCALENDAR')]:
    status, headers, body = fetch(path)
    assert status == 200 and marker in body, (path, status, body)
    assert headers['Content-Type'].startswith(mime)
    assert headers['Cache-Control'] == 'no-cache'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert "default-src 'none'" in headers['Content-Security-Policy']
    assert fetch(path, 'HEAD')[0] == 200
    assert fetch(path, 'POST')[0] == 403
for path in ['/config.yaml', '/calendar-data.json', '/index.html', '/.calendar-secret',
             '/../etc/passwd', '/%2e%2e/etc/passwd', '/cruises.ics/anything']:
    assert fetch(path)[0] in (400, 404), path
# Atomic replacements must become visible, even with a conditional request in the same second.
c.calendar_atomic_write(directory / 'cruises.ics', b'BEGIN:VCALENDAR\r\nX-WR-CALNAME:Updated\r\nEND:VCALENDAR\r\n', mode=0o644)
status, headers, body = fetch('/cruises.ics', headers={'If-Modified-Since': 'Wed, 31 Dec 2099 23:59:59 GMT'})
assert status == 200 and b'Updated' in body
# Even a symlink placed in the export directory cannot expose another mounted file.
(directory / 'report.txt').unlink()
(directory / 'report.txt').symlink_to('config.yaml')
assert fetch('/report.txt')[0] in (403, 404)
print('Static web server smoke checks passed')
