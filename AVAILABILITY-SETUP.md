# Royal Caribbean reservation availability setup

This fork can monitor booked Royal Caribbean sailings for dining and entertainment
reservation releases. It uses the checker's existing authentication, request helper,
scheduler, and Apprise notifications. It does not reserve, purchase, modify, or
cancel anything.

For the detailed configuration contract and detector behavior, see
[docs/reservation-alerts.md](docs/reservation-alerts.md).

## Dedicated availability container

The supplied Compose configuration can run availability checks without duplicating
normal cabin/add-on price alerts. Copy the sample and keep the data directory
persistent:

```sh
cp SAMPLE-availability-config.yaml config.availability.yaml
mkdir -p data
chmod 600 config.availability.yaml
```

Copy your Royal Caribbean credentials and Apprise URL into the file. The default
dedicated-container configuration uses:

```yaml
availability:
  only: true
  dryRun: true
  stateFile: /app/data/reservation-availability.json
  reservations:
    - reservation: "1234567"
      dining: true
      shows: true
      notifyOnReopen: false
```

`only: true` is a fork-only execution switch for the dedicated availability
container. Omit it or set it to `false` when availability should run alongside
normal price checks.

## Category selection

The common configuration is intentionally simple:

- `dining: true` discovers the sailing's complete Dining catalog and checks every
  product whose returned type is exactly `pt_dining`.
- `shows: true` discovers the Show catalog and checks every product whose returned
  type is exactly `pt_show`.
- `false` disables that category.

Royal's Dining category can also contain packages and onboard activities. Those are
silently ignored and are not queried as restaurant reservations because their
returned product type differs from `pt_dining`.

For selective monitoring, provide product IDs:

```yaml
availability:
  only: true
  dryRun: true
  stateFile: /app/data/reservation-availability.json
  reservations:
    - reservation: "1234567"
      dining:
        products:
          - "UT_RAILDINNER"
      shows: true
```

A selected product that is absent from a complete catalog can become unavailable
for reopen tracking. Unrelated products are ignored and are not interpreted as
closed.

## State migration

The prior fork build stored reservation alerts in a watch-scoped JSON schema under
`reservation-availability.json`. The reservation/category model uses a different
scope identity and does not import that state.

Before deploying this build, stop the checker and delete the existing
`/app/data/reservation-availability.json` file (and its stale `.lock` sidecar if
present). Keep the configured path unchanged:

```yaml
stateFile: /app/data/reservation-availability.json
```

The new build recreates the file with the reservation/category `scopes` schema.
The first live run can send alerts for products that are already available;
subsequent successful checks suppress repeats.

The new JSON contains a version number and a `scopes` mapping. Scope keys are hashed
from account, sailing, booking, and category context. Credentials, guest names, and
raw API responses are not stored.

## First run

Build and validate configuration without signing in:

```sh
docker compose -f compose.availability.yaml build
docker compose -f compose.availability.yaml run --rm royal-availability check --validate-config
```

Then perform a live diagnostic run while `dryRun: true`:

```sh
docker compose -f compose.availability.yaml run --rm royal-availability check
```

A dry run does make authenticated read requests to Royal's APIs, but it does not
send availability notifications or advance reservation-availability state. Compare
the returned products and times with Cruise Planner.

When the results look correct, set `dryRun: false` and start the service:

```sh
docker compose -f compose.availability.yaml up -d
docker compose -f compose.availability.yaml logs --tail=100 -f royal-availability
```

For an immediate scheduled-container check:

```sh
docker compose -f compose.availability.yaml exec royal-availability ./entrypoint.sh check
```

## Availability semantics

The detector uses dated offering inventory. Existing reservations, personal schedule
conflicts, and guest conflict metadata do not suppress a release alert.

Live Icon of the Seas and Utopia of the Seas captures validated normal restaurant
reservations, My Time Dining, mixed Dining catalogs, and Royal Railway — Utopia
Station. Royal Railway used `pt_dining` and returned in-stock offerings even with
`active: false` and personal conflicts, so neither field is treated as a booking
gate.

`stockLevel: 9999` is an API indicator rather than a literal table or seat count.
Dining inventory is not a guarantee that Royal can seat the full party.

Incomplete pagination, malformed responses, HTTP/GraphQL failures, and unrecognized
inventory fields are `unknown`, not sold out. Unknown checks preserve prior state.
A notifier must report success before an alert is acknowledged.

## Notifications

Console and web-report output are grouped by account, then sailing, then Dining/Shows. The sailing line displays the formatted sail date and ship name when available, with the ship code as a fallback. Apprise's routine transport-success chatter is hidden for availability notifications; warnings and failures are still shown.

Newly available products are grouped into one alert per reservation category. Each
product previews up to six times and links to the sailing's Cruise Planner category.
The console retains all returned times.

If the notification service has small message limits, add Apprise's
`overflow=split` option to the notification URL.

## Persistent storage

Keep `/app/data` bind-mounted across container replacements. The reservation state
file is separate from cabin availability state and price-history SQLite data.

Configuration edits to a bind-mounted file may require a container restart if your
editor replaces the file inode. Schedule or timezone changes generally require the
Compose service to be recreated.
