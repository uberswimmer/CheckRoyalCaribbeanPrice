# Scheduled Activities & Reservations

This optional report lists activities **already booked** for selected Royal
Caribbean reservations: free shows, dining, spa appointments, excursions and
other scheduled purchases returned by Royal's personal itinerary endpoint.
It does not book, cancel or change anything on Royal's website.

This is not `reservationAlerts` (inventory available to book), nor the public
onboard activity schedule in `BrowseRoyalCaribbeanPrice.py`.

## Configuration

```yaml
scheduledActivities:
  reservations: ["1234567", "7654321"]
  stateFile: "data/scheduled-activities.json"
```

- Omit `scheduledActivities` to disable it. There are no additional requests or
  state-file changes when disabled. A configured reservation list must be nonempty;
  duplicate IDs and unrecognized option keys are errors.
- Each selected reservation must be visible to a configured Royal account.
  Guests belonging to other reservations are excluded, even if Royal returns them.
  Shared sessions across selected cabins appear once, with their guests combined.
- `stateFile` is optional; the example shows its default. Choose a writable path,
  separate from cabin/reservation-alert state and price-history files. Use one
  state file per checker configuration. For Docker, put it on persistent storage.
- Existing account login, booking discovery and API retry settings are reused.
  No new package, scheduler, notification service or separate execution mode is
  needed. Neither `reservationAlerts` nor Apprise needs to be enabled.
- Price thresholds, ignored price alerts and `displayCruisePrices: false` do not
  suppress the schedule. Celebrity pricing remains supported, but this feature
  does not call Celebrity's itinerary endpoint.
- An effective `casinoOffersOnly: true` account does not fetch bookings or
  activities. Another fully checked account must expose the selected reservation.

## Report

With `dateDisplayFormat: "%Y-%m-%d"`, fictional output looks like:

```text
Scheduled Activities & Reservations
  Local times as returned by Royal; confirm in Cruise Planner. No timezone conversion applied.
  ICON OF THE SEAS (2099-10-10)
    Reservation 1234567: Updated 2099-09-01T12:00:00+00:00
    2099-10-11  10:00–11:30  Example spa treatment
      Alex | Spa
    2099-10-11  20:15–21:05  Example show
      Alex, Sam | Example Theater
```

Sailings are sorted chronologically, then activities by start time and title.
Activity dates follow `dateDisplayFormat`; times use 24-hour notation. Capture
timestamps are UTC, whereas activity times are the local wall-clock values
returned by Royal, not inferred ship time or converted to your computer's zone.
Always confirm the schedule in Cruise Planner.

Explicit end times are used, even when a title suggests a different duration.
Missing or equal end times produce a start time only. Overnight end times include
the end date. At-your-leisure activities are labeled without inventing an appointment
time. Only recognized beverage, internet and package purchases with explicitly
null start/end times and no other scheduling information are omitted. Dated
packages remain included; an appointment missing its time is an error.

## Failure and preservation behavior

The checker stores a normalized, allowlisted snapshot for each selected
reservation. API errors, warnings, malformed appointments, ambiguous sailing
identity and missing bookings do not erase its last successful capture.
Retained data is labeled **STALE**, with the previous capture timestamp. A new
reservation whose first request fails is reported as unavailable, not as a
successful empty schedule.

Only a complete successful refresh establishes that a previously booked activity
has disappeared or been canceled. Linked cabins are checked for conflicting
session details before a sailing's updates are committed. Conflicts preserve
the previous sailing snapshots and produce a warning. A later consistent refresh
can update them together.

Other checks and accounts continue after a scheduled-activity failure. The price,
check-in and schedule output finishes before the run reports partial failure
(existing exit code 2). A missing-booking warning can reflect a login failure,
account selection or `casinoOffersOnly`, not necessarily an incorrect ID.

Snapshot writes use the existing cross-platform sidecar lock and atomic JSON
replacement. Invalid existing state is not silently reset or overwritten.
Completed sailings are not polled or included in the upcoming report; their saved
snapshots remain until their reservation is removed from configuration. Removing
a reservation explicitly prunes its saved data on the next enabled run. Disabling
the feature leaves the file untouched.

## Readable identity and privacy

State version 1 uses readable JSON-array keys:

- Snapshot: `[ship, sailDate, reservationId]`.
- Activity: `[ship, sailDate, productId, itineraryItemId]`.
- Guest: `[reservationId, guestId]`.

Times and titles are not part of activity identity. A reschedule keeps its
identity; a replacement booking with a new itinerary item ID has a new identity.
There are no hashes or legacy hashed-key compatibility paths. JSON-array encoding
keeps identifiers readable without ambiguous delimiter concatenation.

The snapshot structure and strict validation can also support a later calendar
consumer. This feature does **not** export ICS or generate calendar UIDs, and does
not migrate fork-specific calendar files.

**The state and console/log output contain personal travel information.** State
includes readable reservation/guest/product/session IDs, first names, activity
titles, locations and times. It is not anonymized. Raw API responses, credentials,
birth dates, surnames and order codes are not stored by this feature. Keep state,
logs and backups private; sanitize them before sharing an issue or test fixture.

## Request and performance costs

Normally there is one extra personal-itinerary GET per selected reservation per
run, not one request per activity or guest. Successful captures are reused across
linked accounts. API retries add attempts; a failed capture may also be retried
through another account, at most once per account/reservation/sailing per run.
Requests share the existing one-second reservation-request pacing and retry policy.

Two selected reservations checked twice daily normally add four requests daily,
before retries. No extra login, catalog, per-product eligibility or port-itinerary
request is needed. Parsing/grouping and JSON storage scale with the returned
activity and guest counts. Run frequency remains controlled by your existing
scheduler.
