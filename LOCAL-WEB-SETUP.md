# Local reports and calendar subscription

The optional report server serves saved files over HTTP on your LAN. It permits
direct access without authentication. OPNsense Nginx is not involved; a reverse
proxy can be added later if external access is wanted. Nothing is forwarded from
the Internet by this Compose file.

The checker continues using its existing schedule. A separate Nginx container
serves three routes from a read-only export directory:

| Route | Content |
| --- | --- |
| `/` | Latest check's formatted report, with colors, spacing, start/end timestamps and status |
| `/report.txt` | Latest check as plain text |
| `/cruises.ics` | Calendar subscription feed |

This is a saved report, not an interactive console. Refresh the browser after a
check. Opening a page does not run the checker or contact Royal Caribbean.

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
  sailings:
    - ship: IC
      sailDate: "2099-10-10" # Fictional example; substitute your booked sailing
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

Open `http://YOUR_DOCKER_SERVER_LAN_IP:8088/`. Until the first report is written,
that route returns 503. The calendar returns 404 until generated. If an existing
public directory is not readable by the server, check its directory permissions.
If port 8088 is in use, choose another `REPORT_PORT`.

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
state and price history outside the server's mount. The server has no Docker
socket, checker process, upload endpoint or command execution endpoint. Unknown
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
