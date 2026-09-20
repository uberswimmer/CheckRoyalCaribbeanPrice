# Dining and entertainment reservation-release alerts

Optionally watch a booked Royal Caribbean sailing for dining or show reservations
to open. This checks **dated offerings with reported inventory**, rather than
whether a product is visible in Cruise Planner or has a price. Free shows can
therefore trigger an alert too.

The feature is disabled unless `availability` is configured. It runs alongside
normal price checks, using the existing account login, schedule, request retries,
and per-account/global Apprise settings. It does not reserve anything or create a
cart. Celebrity is not supported.

## Configuration

Add this block to your existing configuration, replacing the example reservation
numbers and dining product code. The reservations must be linked to one of your
configured Royal Caribbean accounts.

```yaml
availability:
  dryRun: true
  stateFile: "data/reservation-availability.json"
  watches:
    - id: "summer-shows"
      name: "Summer cruise shows"
      reservation: "1234567"
      category: "show"
    - id: "winter-dining"
      name: "Winter cruise dining"
      reservation: "7654321"
      category: "dining"
      product: "YOUR_DINING_PRODUCT_CODE"
      notifyOnReopen: false
```

Run your usual check and compare the reported times with Cruise Planner. With
`dryRun: true` (the default), availability checks use live read requests but do
not send availability notifications or read/write notification state. This is
**not a global dry run**: existing price alerts and `appriseTest` still work as
configured. Set `dryRun: false` to enable release notifications once the output
looks correct, and configure Apprise to receive them.

| Setting | Behavior |
| --- | --- |
| `id` | Required, stable, unique watch identifier. Changing it starts a fresh watch. |
| `name` | Optional label; defaults to `id`. |
| `reservation` | Required booking number. Add separate watches for multiple cruises. |
| `category: show` | Discover all show products for the booking; optionally specify `product` to watch one. |
| `category: dining` | Requires an exact `product` code from that sailing's Cruise Planner product URL, as with existing price watches. Codes and support can differ by ship and product. |
| `enabled: false` | Skip this watch; defaults to `true`. |
| `notifyOnReopen: false` | Default: alert once per product in this watch, account, booking and sailing. Newly discovered products can trigger later alerts. |
| `notifyOnReopen: true` | Also alert after a confirmed closure and subsequent reopening. Failed or uncertain checks do not re-arm an alert. |
| `stateFile` | JSON file used to suppress repeats across runs and restarts. Defaults to `data/reservation-availability.json`. |

The first live check alerts for products that are already available. An alert is
about a product's release, not every additional session or change in its times.
Existing reservations, exhausted guest allowances and personal scheduling
conflicts do not hide a release. You must confirm that an offering is suitable
and book it yourself. Dining stock is not a guarantee of a table for your party;
not every dining product exposes usable dated offerings through this endpoint.

## Notifications and state

Newly available products are grouped into one alert per watch. Each product
previews up to six times, grouped by date using `dateDisplayFormat`, with a link
to the sailing's Cruise Planner category. The console shows all returned times.
Times preserve Royal's wall-clock values; no timezone conversion is performed.
For large notifications, Apprise's `overflow=split` URL option can avoid message
truncation by services with small limits.

Keep the state file on persistent storage. In Docker, mount a writable directory
at `/app/data`, or configure an absolute `stateFile` path in an existing persistent
mount. The file is separate from cabin-alert JSON and optional price-history
SQLite storage; no additional database is required. Do not point these features
at the same file. Deleting the reservation state or changing a watch's identity
can repeat previously delivered alerts.

State stores a hashed account/booking/watch context, product IDs, last confirmed
availability and notification acknowledgements. It does not store credentials,
guest names or raw API responses. Notification links contain booking context;
handle them as personal information.

A sidecar lock covers reading state, deciding/sending notifications and atomically
replacing the JSON file. Invalid state or lock contention is reported without
resetting saved acknowledgements. Apprise must confirm success before an alert
is acknowledged. Failed delivery retries on a later run. A crash or disk failure
after delivery but before saving can produce a duplicate alert; delivery and
local persistence cannot be one atomic operation.

`unknown` means failed, incomplete or unrecognized evidence, not sold out. A
product is marked absent only after a complete catalog read. Previously saved
state is retained for unknown products. Missing reservations, failed checks,
state errors or unconfirmed notifications are reported after normal price
outputs, using the existing partial-failure exit status so scheduled failures
remain visible.

## Validation

Tests use synthetic response fixtures and mocked transports, including inventory
interpretation, catalog pagination, per-account isolation, failed notification
retries, JSON validation, concurrent processes, atomic-save failures and normal
price-report completion. They do not contact Royal or send real notifications.
Entertainment release behavior has been exercised in a running fork. Dining
response interpretation is covered by captured-contract fixtures; this is not a
claim of live validation for every dining product, including My Time Dining.
