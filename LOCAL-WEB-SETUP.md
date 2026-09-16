# Local reports and calendar subscription

The optional report server serves saved files over HTTP on your LAN. It permits
direct access without authentication. An optional **Run check now** button starts
the checker's normal run. Nothing is forwarded from the Internet by this Compose file.

The checker continues using its existing schedule. A separate Nginx container
serves saved exports from a read-only directory:

| Route | Content |
| --- | --- |
| `/` | Latest check's formatted report, with colors, spacing, start/end timestamps and status |
| `/report.txt` | Latest check as plain text |
| `/cruises.ics` | Calendar subscription feed |

The page contains a saved report and, when enabled, a fixed check button. Opening
the page does not run the checker or contact Royal Caribbean. While the page is
open, the button checks local run status and refreshes the report when a run ends.
Without run control, refresh the browser to see later reports.

## Enable generation

Add one setting to your existing `config.availability.yaml`:

```yaml
reportDirectory: /app/data/public
```

Keep your existing accounts, watches, notification settings and calendar block.
The calendar's private capture directory should remain separate:

```yaml
calendar:
  enabled: true
  outputDirectory: /app/data/calendar
  reservations:
    - "1000001" # Fictional example; substitute your reservation number
```

There is still only one configuration file mounted at `/app/config.yaml`. See
[calendar setup](CALENDAR-SETUP.md) for event details. Reporting works with both
full checks and availability-only checks; it reports whichever mode ran.
`--validate-config` and notification self-tests leave the saved report alone.
An availability dry run still produces a report and an enabled calendar export.

Before deploying, create the public directory on the Docker host:

```sh
mkdir -p /home/docker/cruise-availability-checker/data/public
chmod 755 /home/docker/cruise-availability-checker/data/public
```

Do not change permissions recursively on the rest of `data`. Exported files are
created readable by the unprivileged web-server user. Calendar capture and state
files retain their private permissions.

## Portainer deployment

Use [compose.local-web.yaml](compose.local-web.yaml) to update the existing
availability-checker stack. It includes both the checker and the report server.
Do not deploy a second writer alongside the current availability checker using
the same data directory. The original upstream price-checker stack can stay as is.

Set these Portainer stack environment variables, using your own fork owner:

```text
CHECKER_IMAGE=ghcr.io/YOUR_GITHUB_OWNER/royalcaribbean-availability:latest
REPORT_IMAGE=ghcr.io/YOUR_GITHUB_OWNER/royalcaribbean-availability-reports:latest
LAN_IP=YOUR_DOCKER_SERVER_LAN_IP
```

Optional variables default to the existing environment:

```text
CHECKER_HOME=/home/docker/cruise-availability-checker
TZ=America/New_York
CRON_SCHEDULE=0 7,19 * * *
REPORT_PORT=8088
```

The report image is published along with the checker when the PR is merged to
`main`. PR checks build and exercise it without publishing. Do not deploy the
new image name until that publication has succeeded. A new GHCR package may need
its visibility set to Public before an unauthenticated Portainer pull succeeds.
Existing Watchtower can update these images according to its existing selection
rules. This stack does not create another Watchtower service.

In the checker container's Portainer console, run:

```sh
./entrypoint.sh check --validate-config
./entrypoint.sh check
```

Open `http://YOUR_DOCKER_SERVER_LAN_IP:8088/`. Before the first report is written,
the page offers the check button when control is enabled. The calendar returns 404 until generated. If an existing
public directory is not readable by the server, check its directory permissions.
If port 8088 is in use, choose another `REPORT_PORT`.

## Run check now

The supplied Compose file enables run control. For an existing Portainer stack,
pull both updated images and add these settings to the checker service, retaining
its current timezone, schedule, mounts and image:

```yaml
    stop_grace_period: 20s
    environment:
      # Keep the existing TZ and CRON_SCHEDULE entries here too.
      CHECKER_WEB_ENABLED: "true"
      CHECKER_WEB_ORIGIN: "http://${LAN_IP}:${REPORT_PORT:-8088}"
```

Redeploy the stack once so the environment changes take effect. Watchtower image
updates alone cannot add these settings. Both services must share the Compose
network, with the checker reachable as `cruise-availability-checker`.
Use the exact configured report address in the browser. A different hostname or
port will not be accepted for control requests. No additional host port is needed.

The button runs the same `CheckRoyalCaribbeanPrice.py` command as the normal
schedule, using `/app/config.yaml` and normal notifications. With
`availability.only: false`, this includes price checks and enabled availability
and calendar features. With `only: true`, it follows availability-only mode.
There is no browser option to change configuration or send command arguments.

The page shows running/completed/failed status and refreshes after completion.
Scheduled runs are visible too. If a run fails before it can write a report, the
control status shows failure and the saved report can still be from the prior run;
check container logs in that case. The interface does not stream console output.

Manual requests, cron and `./entrypoint.sh check` share an OS lock in
`/app/data/run-control`. A busy invocation is skipped, not queued, so a scheduled
check arriving during a manual run will not overlap it. A skipped console/cron
invocation exits with code 75. Direct `python CheckRoyalCaribbeanPrice.py` commands
bypass this Docker wrapper; use the entrypoint for manual Docker checks.
Web requests also have a 60-second minimum between start times. An interrupted
run is detected when its saved status says running but its process lock is gone.

Only the latest small status file and two lock files are kept, outside public
exports. This adds no report history. Disabling `CHECKER_WEB_ENABLED` and
redeploying removes the control listener; scheduled checks and report serving
continue. Docker's scheduler and web controller are supervised together so an
unexpected exit of either causes the container to restart.

Anyone who can reach the LAN page can deliberately start a check. The controller
requires the configured Host/Origin and a per-startup request token to reject
requests from unrelated websites. Tokens are not passwords or user authentication.
GET/status requests cannot run checks, and POST accepts no body or arguments.
Nginx proxies only `/api/check` to the internal listener on port 8081. Keep that port
unpublished. The browser script is a fixed image asset, and report text remains
HTML-escaped under a policy that forbids inline scripts and framing.

## Calendar subscription

On iPhone, add a **subscription calendar** using
`http://YOUR_DOCKER_SERVER_LAN_IP:8088/cruises.ics`. Subscribe from a device on the
LAN; a cloud service cannot fetch a private LAN address. Importing a downloaded
file creates a snapshot and does not subscribe to subsequent updates.

Refresh timing is controlled by the calendar app. The server permits revalidation
and returns current file contents on each request. Previously downloaded events
are expected to remain visible away from home, but offline caching and refresh
error behavior need to be verified on your device. Test a refresh on Wi-Fi,
viewing events off Wi-Fi, then another refresh after reconnecting. A calendar
client may display an unavailable-server message while away from the LAN.

## Data handling and failure behavior

Only `data/public` is mounted into the report container. The checker copies the
`.ics` there, leaving `calendar-data.json`, account configuration, availability
state and price history outside the server's mount. The report server has no Docker
socket, checker process, account configuration or upload endpoint. The optional
control endpoint accepts only a fixed check request. Unknown
paths return 404; directory listings and symlink serving are disabled.

The report includes the personal information already printed by the checker,
such as passenger names, account email, reservation numbers and prices. HTML
escaping prevents that output from becoming executable page content. This is
not anonymization. Anyone who can reach the published port can read the report
and calendar. LAN binding chooses an interface, not a client-subnet allowlist;
any routed networks permitted by your network rules may also reach it.

The export contains only the latest run, capped at two million log characters
with an explicit truncation notice. Existing console and `logFile` output remain
available. Report capture precedes plaintext log filters so colors are preserved.
Files are replaced atomically; the web mount is a directory so replacements are
visible immediately. No growing web log archive is created.

A new run writes a Running report, then replaces it with Completed or Failed at
exit. Run failures and Python-level interruptions retain a failed report. A hard
kill or power loss may leave Running with its original start timestamp. A config
parse error or a failure before report initialization leaves the previous report;
check its timestamp and container logs. Upstream operations that log and skip a
problem without failing the run still result in Completed; read the report for
those warnings. No new interpretation of upstream success is added.

After failed checks, a previously generated calendar can remain available and
may contain older data. The report explicitly calls out this possibility. Calendar
publication does not change the file's modification time if content is unchanged.
Disabling calendar generation removes the public feed after the next reported run,
while preserving private calendar files. Removing `reportDirectory` stops report
updates but leaves exported files in place; remove the web service or its public
files if access should also stop. Use one writer per export directory.
