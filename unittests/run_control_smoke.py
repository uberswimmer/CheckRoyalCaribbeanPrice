"""Exercise the real Docker entrypoint and Nginx proxy using the fixture checker."""
import json
from pathlib import Path
import subprocess
import sys
import time
from playwright.sync_api import sync_playwright
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

base, directory, container = sys.argv[1], Path(sys.argv[2]), sys.argv[3]


def fetch(path='/api/check', method='GET', token=None, origin=None, data=None):
    headers = {}
    if origin: headers['Origin'] = origin
    if token: headers['X-CSRF-Token'] = token
    if method == 'POST' and data is None: data = b''
    try:
        response = urlopen(Request(base+path, method=method, headers=headers, data=data), timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read()
        return response.status, json.loads(body) if response.headers.get_content_type() == 'application/json' else body


def wait_for(predicate):
    for _ in range(80):
        try:
            if predicate(): return
        except (URLError, OSError):
            pass
        time.sleep(0.25)
    raise AssertionError('Container did not reach expected status')


wait_for(lambda: fetch()[0] == 200)
assert fetch('/')[0] == 200 and b'No report has been generated' in fetch('/')[1]
assert fetch('/run-control.js')[0] == 200
token = fetch()[1]['token']
assert fetch(method='POST',token=token,origin='http://untrusted.invalid')[0] == 403
assert fetch(method='POST',origin=base)[0] == 403
assert fetch(method='POST',token=token,origin=base,data=b'command=anything')[0] == 400
assert fetch('/api/check?command=anything',method='POST',token=token,origin=base)[0] == 404
assert not (directory/'fixture-count').exists()
playwright = sync_playwright().start()
browser = playwright.chromium.launch(channel='chrome', headless=True, args=['--no-sandbox'])
page = browser.new_page()
errors = []
page.on('pageerror', lambda error: errors.append(str(error)))
# Simulate a saved report from before the feature. Nginx adds the asset without
# requiring a Portainer check first or rewriting any existing report file.
(directory/'public/index.html').write_text('<!doctype html><html><head><title>Prior report</title></head>'
    '<body><h1>Cruise checker report</h1><p>Prior saved report</p></body></html>')
page.goto(base)
button = page.get_by_role('button',name='Run check now')
button.wait_for(state='visible')
with page.expect_response(lambda response: response.url.endswith('/api/check') and response.request.method == 'POST') as started:
    button.click()
assert started.value.status == 202
wait_for(lambda: (directory/'fixture-count').exists())
assert fetch()[1]['state'] == 'running'
assert fetch(method='POST',token=token,origin=base)[0] == 409
skipped = subprocess.run(['docker','exec',container,'./entrypoint.sh','check'],capture_output=True,timeout=10)
assert skipped.returncode == 75, skipped.stdout
assert (directory/'fixture-count').read_text() == 'run\n'
(directory/'fixture-finish').write_text('0')
wait_for(lambda: fetch()[1]['state'] == 'completed')
assert b'Fixture check Completed' in fetch('/')[1]
page.wait_for_function("document.body.textContent.includes('Fixture check Completed')")
page.wait_for_function("document.querySelector('[role=status]')?.textContent.includes('Last check completed')")
assert button.is_disabled()  # Cooldown after the automatic refresh.
assert not errors, errors
browser.close(); playwright.stop()
assert fetch(method='POST',token=token,origin=base)[0] == 429
for path in ['/run-control/status.json','/status.json','/config.yaml','/fixture-count']:
    assert fetch(path)[0] == 404

# The cron command uses the same wrapper; an existing scheduled/console run blocks
# web requests. Its nonzero exit is visible even though docker exec is detached.
(directory/'fixture-finish').unlink()
subprocess.run(['docker','exec','-d',container,'python','/app/run_control.py','check'],check=True,timeout=5)
wait_for(lambda: fetch()[1]['state'] == 'running')
assert fetch(method='POST',token=token,origin=base)[0] == 409
(directory/'fixture-finish').write_text('2')
wait_for(lambda: fetch()[1]['state'] == 'failed')
assert b'Fixture check Failed' in fetch('/')[1]

# Restart rotates request tokens, retains cooldown, and leaves saved reports readable.
subprocess.run(['docker','restart',container],check=True,timeout=25,capture_output=True)
wait_for(lambda: fetch()[0] == 200)
assert fetch()[1]['token'] != token
assert fetch(method='POST',token=token,origin=base)[0] == 403
assert fetch(method='POST',token=fetch()[1]['token'],origin=base)[0] == 429
subprocess.run(['docker','stop',container],check=True,timeout=25,capture_output=True)
assert fetch('/')[0] == 200
assert fetch()[0] in (502,504)
print('Run control Docker/proxy/browser smoke checks passed')
