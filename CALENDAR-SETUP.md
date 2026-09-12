# Local cruise calendar export

This opt-in feature writes `cruises.ics` and an allowlisted `calendar-data.json`
capture during the existing scheduled run. It creates no web server, subscription
URL, external calendar events, or additional schedule. Keep calendar access/hosting
as a separate deployment step.

## Configuration

Add this block to your existing configuration, substituting your booked sailing:

```yaml
calendar:
  enabled: true
  outputDirectory: /app/data/calendar
  sailings:
    - ship: IC
      sailDate: "2099-10-10" # Fictional example; use your sailing date
      departureTimeZone: America/New_York
```

Use Royal's two-letter ship code and an IANA departure-port time-zone name. The
zone is required per sailing; the checker does not guess it from the Docker TZ.
The `tzdata` dependency supplies the database on systems without OS time-zone data.
Existing configurations without `calendar` behave unchanged. Relative output paths
remain relative to the working directory, like the existing output settings.

For the existing Portainer deployment, `/app/data` is already persistent. The
calendar files therefore appear in its host `data/calendar` subdirectory. No
additional mount or service is needed for local generation. Only one checker
process/container should write to a given calendar directory at a time.

Run `./entrypoint.sh check --validate-config`, then `./entrypoint.sh check`.
Validation does not fetch calendars or create export files. Calendar capture works
in both the normal combined run and `availability.only: true`. It still works when
all availability watches are disabled. `availability.dryRun` applies only to
availability notifications/state; an enabled calendar export writes its own files.

Only the configured sailings found in authenticated Royal Caribbean bookings are
captured. The checker reuses its existing login session. It requests itinerary and
check-in information once per sailing per run, even for multiple linked accounts
or cabins. These are two additional read requests; no carts or bookings are changed.

## Events and times

- Embarkation: the published departure time, excluding the arrival placeholder.
- Port visit: published arrival through departure, including tendered visits.
- Disembarkation: the published arrival time, excluding the departure placeholder.
- Sea days: excluded using Royal's `CRUISING` classification.
- Final payment: an all-day event for each booking. Existing date overrides,
  market/duration rules and normal-run payment status are reused. The description
  distinguishes configured, booking-reported and estimated dates. A paid booking
  retains its deadline with a Paid description. In availability-only mode, payment
  status uses booking fields and `reservationsPaidInFull`; the price ledger is not
  fetched just for the calendar, so the status may be unknown.
- Check-in: 00:01 on the opening date in the configured departure-port zone,
  converted to a UTC calendar instant with daylight-saving rules. Its description
  retains the local date/time and zone. This is a scheduled opening, not confirmation
  that Royal has enabled check-in.

**Check-in field validation is pending a website comparison.** The first build uses
the written date portion of `checkWindowOpenStartDateTime`, then applies 00:01 in
the departure zone. It does not convert Royal's midnight marker through the host
zone, which could shift the date backward. Verify that written date against the
website before relying on the check-in event. If Royal supplies no opening date,
no date is invented. Once an opening was captured, it remains when Royal later
reports check-in open without a date.

Itinerary events use *floating* calendar times: the published clock values remain
unchanged when viewed in another zone. They are labeled published local time,
not guaranteed ship time. A captain may choose a different ship time. A floating
event does not represent an absolute instant, so reminders follow the calendar
client's current zone. Unlike itinerary events, check-in uses an absolute UTC
instant. No calendar alarms are added by this initial build.

## Updates, persistence and privacy

Stable event IDs prevent duplicates. Port events are identified by sailing/day;
changes to the port or times update that day's event. If Royal reorders days, an
event follows the day slot. A revision number changes only when event content does.
Itineraries and check-in are shared across cabins; payment events remain separate.
Cabin numbers label payments, with existing `reservationFriendlyNames` labels taking
precedence. If neither is available, an opaque booking reference distinguishes them.

Failed, empty or malformed itinerary responses retain the last successful itinerary.
Missing bookings do not imply cancellation or deletion. Capture failures are logged
and produce a failed run status after price outputs and calendar generation.
Successfully captured sections can still update while failed sections retain older
data. A confirmed canceled sailing marks its events canceled, even if Royal no longer
returns an itinerary. Removing a sailing from the configuration
removes its events on the next export; disabling export leaves existing files alone.
Bookings that disappear remain in the local capture until their sailing is removed.

Each file is replaced atomically. The JSON capture is written before the `.ics`;
if writing the latter fails, a later run can regenerate it from saved capture data.
A corrupt/unreadable capture is an error, not an instruction to reset history.
Back up both files together if moving the installation.

The capture retains selected itinerary fields, the original opening timestamp,
deadline source/status, capture timestamps and calendar revision data. It does not
store credentials, session tokens, raw booking numbers, passenger lists or prices.
Sailing details, cabin numbers and configured friendly labels are personal travel
information. Opaque booking hashes are identifiers, not access controls. Keep both
files outside Git and defer sharing until calendar access is configured.

## Requested verification capture

For one future sailing whose check-in is not yet open:

1. Screenshot the displayed opening date, ship, sail date and departure port.
2. In Firefox Network, reload the page and filter for `voyages` or `enriched`.
3. Locate `/ships/voyages/<ship code><YYYYMMDD>/enriched`; save its response JSON
   and copy the request URL. No headers, cookies or authentication tokens are needed.
4. An optional cropped screenshot of the website's final-payment deadline provides
   an independent comparison. Personal names, booking numbers and amounts can be
   removed. If no deadline is shown, the existing config override remains usable.

Itinerary request fields and clock values were confirmed against one live Royal
response and its matching Cruise Planner screenshot. Automated tests use fictional
sailings; live check-in date semantics and importing into Apple Calendar still need
validation. Calendar hosting and notifications are outside this PR.
