# Local cruise calendar export

This opt-in feature writes `cruises.ics` and an allowlisted `calendar-data.json`
capture during the existing scheduled run. It creates no external calendar events
or additional schedule. Optional LAN hosting and a formatted report are available
through the separate service described in [local web setup](LOCAL-WEB-SETUP.md).

## Configuration

Add this block to your existing configuration, substituting your reservation numbers:

```yaml
calendar:
  enabled: true
  outputDirectory: /app/data/calendar
  reservations:
    - "1000001" # Fictional examples; use your reservation numbers
    - "1000002"
```

The checker resolves the ship and sailing date from the bookings already retrieved
for your configured Royal Caribbean accounts. No additional booking-discovery API
call is needed. Only listed reservations are included. If you want payment deadlines
for multiple cabins, list each reservation; cabins on the same sailing share one
itinerary and check-in event. Quoted numbers are recommended; YAML integers also work.
An enabled calendar requires a nonempty selection, so omitting it does not include
all bookings automatically.

The earlier `sailings` list of `{ship: IC, sailDate: "2099-10-10"}` entries remains
supported for selecting every retrieved booking on those sailings. Use either
`reservations` or `sailings`, not both. Existing configurations
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

Only selected bookings/sailings found in authenticated Royal Caribbean accounts are
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
returns an itinerary. Removing a reservation removes its payment event on the next
export. The shared itinerary/check-in remain while another selected reservation uses
that sailing. A selected reservation that temporarily disappears retains its saved
calendar data and produces a warning identifying its list index. A confirmed change
to that reservation's ship/date moves its calendar selection to the new sailing.
With the older ship/date selection, removing a sailing removes all its events.
Disabling export leaves private files alone; local web publishing removes the public
feed on the next reported run. Missing selected bookings are retained until removed
from the selection, rather than being inferred canceled.

Each file is replaced atomically. The JSON capture is written before the `.ics`;
if writing the latter fails, a later run can regenerate it from saved capture data.
A corrupt/unreadable capture is an error, not an instruction to reset history.
Back up both files together if moving the installation.

The capture retains selected itinerary fields, the existing checker's opening datetime,
deadline source/status, capture timestamps, calendar revision data and hashed
reservation-to-sailing bindings used to retain data when a booking is missing. It does not
store credentials, session tokens, raw booking numbers or prices. Activity export additionally retains participating
guest first names and hashed guest/session identifiers when enabled.
Sailing details, cabin numbers and configured friendly labels are personal travel
information. Opaque booking hashes are identifiers, not access controls. Keep both
files outside Git. Optional local hosting publishes only the ICS file from this
capture directory; it does not publish the JSON capture.

## Validation

Itinerary request fields and clock values were confirmed against one live Royal
response and its matching Cruise Planner screenshot. The existing checker's summary
already reports the check-in opening date/time, which is reused directly. Automated
tests cover reuse without extra requests, preservation of midnight and UTC offsets,
linked bookings, stale-data retention, updates and serialization. Importing the
result into Apple Calendar is still a useful deployment check. No additional Royal
website captures are required to implement this reuse. See local web setup to
subscribe to the generated feed from your LAN.

The availability console section uses separate spacer records between sections
and watches, nested indentation for account/watch/result/time, and reports completion
before the check-in/payment table. Failures still allow price summaries and exports
to finish before the run exits nonzero.

## Booked activities and reservations

Add `includeActivities: true` to the existing `calendar` block:

```yaml
calendar:
  enabled: true
  outputDirectory: /app/data/calendar
  reservations:
    - "1000001" # Fictional example; keep your existing selection
  includeActivities: true
```

This optional setting defaults to false. It adds booked dining, shows (including
free shows), spa appointments, excursions and other scheduled products returned by
Royal's personal itinerary to the same `cruises.ics` feed. No subscription URL,
Compose, web server or schedule change is needed. The same data appears in a
separate **Scheduled Activities & Reservations** section in the console and web
report, with sailings ordered by departure date and activities within each sailing
ordered by date and time, with guest first names and available
venue information. Price-notification exclusions do not exclude calendar activities.

The checker uses its existing authenticated session to make a GET request to
`/en/royal/web/commerce-api/calendar/v1/itinerary` for each selected reservation.
Successful captures are reused across accounts during the run. Although Royal may
return linked bookings, only guests belonging to selected reservations are exported.
List each desired cabin to include its guests. Shared sessions across selected
cabins become one calendar event. With the older ship/date selection, all retrieved
bookings on the selected sailing are included.

Times remain the offset-free clock values supplied by Royal, matching the existing
published-local-time approach. No home, port or ship timezone is inferred. Follow
onboard schedule changes; this endpoint cannot establish the captain's ship time.
Explicit end times take precedence over durations in product names. Missing or equal
end times produce a start-only event. “At Your Leisure” meeting instructions or the
product's leisure flag produce a transparent all-day event, labeled accordingly in
the report, rather than treating a placeholder timestamp as an appointment.

Only guests marked BOOKED are included. A successful, complete response replaces
the last snapshot for that reservation; removed or canceled sessions become
`STATUS:CANCELLED` events. A failed or malformed response retains the previous
snapshot and clearly marks previously captured activities in the report.
Capture-failure diagnostics identify request failures, API errors/warnings or the
invalid response field without printing raw responses or guest identifiers. If a
failure persists, share the full `[Calendar]` warning; a response capture may be
needed to verify an unfamiliar format. Successful empty results can clear a
schedule; errors cannot. Event UIDs and revision numbers
remain stable when session identity is unchanged. Rebooking into another session
cancels the old event and creates a new one. Cancellation records are retained for
selected sailings so subscribed clients can observe them, rather than keeping an
unlimited report history. Removing a selection removes its activity data; setting
`includeActivities: false` removes activity exports on the next completed calendar
run while leaving itinerary, check-in and payment events enabled.

The exported feed and local report now contain first names and personal activity
times when enabled. The private capture stores only normalized activity fields,
first names and opaque identifiers, never raw API responses, birth dates, surnames,
order numbers, booking numbers or authentication tokens. Keep captures and generated
files out of Git. Genie arrangements can appear only when Royal exposes them in the
personal itinerary. This feature does not create or change any Royal reservations.
