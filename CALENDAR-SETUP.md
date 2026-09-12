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
```

Use Royal's two-letter ship code and the sailing date. Existing configurations
without `calendar` behave unchanged. Relative output paths remain relative to the
working directory, like the existing output settings. No separate calendar
time-zone setting or additional runtime dependency is needed.

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
captured. The checker reuses its existing login session. It requests the itinerary
once per sailing per run, even for multiple linked accounts or cabins. Normal runs
reuse the check-in datetime already collected for the final summary table and make
no additional check-in request. Availability-only runs skip that table, so calendar
export calls the existing `get_checkin_info` routine once per sailing instead.
No alternate check-in endpoint or date parser is introduced.

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
- Check-in: the exact timezone-aware datetime returned by the existing checker.
  The same instant is serialized as UTC in the calendar. No 00:01 override, date
  extraction, or departure-zone reinterpretation is applied. When the existing
  summary shows midnight, the calendar retains that midnight instant. A calendar
  client in another time zone may display the corresponding local time. This is
  the reported opening, not confirmation that Royal has enabled check-in.

The existing check-in function remains the source of truth. The summary now retains
its returned datetime alongside the existing display label, instead of discarding
it. If no datetime is returned, no opening is invented; a previously captured opening
is retained. This also covers already checked-in bookings whose normal run skips
another check-in lookup. No additional website capture is required for check-in.

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

The capture retains selected itinerary fields, the existing checker's opening datetime,
deadline source/status, capture timestamps and calendar revision data. It does not
store credentials, session tokens, raw booking numbers, passenger lists or prices.
Sailing details, cabin numbers and configured friendly labels are personal travel
information. Opaque booking hashes are identifiers, not access controls. Keep both
files outside Git and defer sharing until calendar access is configured.

## Validation

Itinerary request fields and clock values were confirmed against one live Royal
response and its matching Cruise Planner screenshot. The existing checker's summary
already reports the check-in opening date/time, which is reused directly. Automated
tests cover reuse without extra requests, preservation of midnight and UTC offsets,
linked bookings, stale-data retention, updates and serialization. Importing the
result into Apple Calendar is still a useful deployment check. No additional Royal
website captures are required to implement this reuse. Hosting remains deferred.

The availability console section uses separate spacer records between sections
and watches, nested indentation for account/watch/result/time, and reports completion
before the check-in/payment table. Failures still allow price summaries and exports
to finish before the run exits nonzero.
