"""CI-only checker replacement. No credentials, Royal requests or notifications."""
from pathlib import Path
import time

root = Path('/app/data')
public = root / 'public'
public.mkdir(exist_ok=True)
with (root / 'fixture-count').open('a') as stream:
    stream.write('run\n')
for _ in range(600):
    if (root / 'fixture-finish').exists():
        code = int((root / 'fixture-finish').read_text())
        break
    time.sleep(0.05)
else:
    code = 1
status = 'Completed' if code == 0 else 'Failed'
(public / 'index.html').write_text('<!doctype html><title>Fixture report</title>'
    '<div id="run-control" hidden></div><script src="/run-control.js" defer></script>'
    '<p>Fixture check ' + status + '</p>')
(public / 'report.txt').write_text(status)
raise SystemExit(code)
