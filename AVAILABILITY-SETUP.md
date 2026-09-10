# Royal Caribbean availability test build 0.1.0

This source build adds entertainment and dining availability monitoring directly to
`CheckRoyalCaribbeanPrice.py`. It does not run or import the Browse script. It uses
the checker's existing authentication, request helper, and Apprise notifications.

The supplied Compose configuration creates a separate service and image. It defaults
to availability-only operation, so it does not duplicate cabin/add-on price alerts.
It uses the existing upstream Dockerfile and scheduler. No additional polling loop
or entertainment-specific schedule is added.

For GitHub-published images and your existing Watchtower, use
[GITHUB-DEPLOYMENT.md](GITHUB-DEPLOYMENT.md) and `compose.watchtower.yaml`.
The local-build instructions below remain available.

## Set up your separate container

These commands assume a Linux Docker host with Docker Compose v2. Extract the ZIP
and open a shell in its `royal-availability` directory.

```sh
cp SAMPLE-availability-config.yaml config.availability.yaml
mkdir -p data
chmod 600 config.availability.yaml
```

Edit `config.availability.yaml`:

1. Copy your Royal Caribbean account credentials and Apprise URL from the existing
   checker. Keep them only in this local configuration.
2. Replace the booking placeholders. Remove or disable watches you do not need.
   A watch targets one booking. Add another watch with a distinct `id` for another
   sailing, including Wonder if desired.
3. Keep `availability.only: true` and `dryRun: true` for the first run.
4. Set the Compose `CRON_SCHEDULE` and `TZ` to match your existing checker. The sample
   defaults to 7 AM and 7 PM in America/New_York; your actual schedule was not provided.

Build and validate syntax without signing in:

```sh
docker compose -f compose.availability.yaml build
docker compose -f compose.availability.yaml run --rm royal-availability check --validate-config
```

Perform one live diagnostic run:

```sh
docker compose -f compose.availability.yaml run --rm royal-availability check
```

A dry run does call Royal's read endpoints, including the POST eligibility query,
using your credentials. It does not notify or advance availability notification state.
Compare the returned product names and times with Cruise Planner. `unknown` means
failed or insufficient evidence, not closed reservations. A failed check exits nonzero
in availability-only mode. Fix failures before relying on monitoring.

When the diagnostic output matches the website, change `dryRun` to `false`, then:

```sh
docker compose -f compose.availability.yaml up -d
docker compose -f compose.availability.yaml logs --tail=100 -f royal-availability
```

The first scheduled check runs at the next cron time. For an immediate check:

```sh
docker compose -f compose.availability.yaml exec royal-availability ./entrypoint.sh check
```

The first live run alerts for products already available, as well as future releases.
Simultaneously discovered products are combined into one notification per watch.
Stop this instance with:

```sh
docker compose -f compose.availability.yaml down
```

The `data` directory remains. Keep it when rebuilding or replacing the container:
`data/availability.sqlite3` prevents repeated alerts across restarts. This is a
separate state file from your production price checker. If configuration edits made
by your editor replace the mounted file rather than modify it in place, restart the
container to refresh the bind mount. Schedule/timezone edits require Compose to
recreate the container (`up -d --force-recreate`).

## Watch behavior

| Option | Behavior |
| --- | --- |
| `category: show` without `product` | Discover all entertainment products for the specified booking. Newly listed shows are picked up on subsequent runs. |
| `category: show` with `product` | Check that exact product ID. |
| `category: dining` | Requires an exact product ID, for example `UT_RAILDINNER` for the captured Utopia Railway product. Do not assume codes carry across ships/sailings. |
| `mode: release` | Default. Alert when dated offerings report inventory. Existing reservations, personal scheduling conflicts, and exhausted guest allowance do not hide a release. |
| `mode: party` | Also require remaining allowance for every configured guest, compliance with the returned guest limit, and no reported conflict for that offering. This is not a checkout or table-size guarantee. |
| `notifyOnReopen: false` | Default. One successfully acknowledged alert per product, watch, account and sailing. Adding a new product can trigger another alert. |
| `notifyOnReopen: true` | Re-arm after a successful observation of unavailability, including catalog disappearance. Unknown/error responses never re-arm. |
| `enabled: false` | Skip the watch. |
| `guests` omitted | Use `passengersInStateroom` from the targeted booking. Never silently fall back to a single guest. |
| Explicit `guests` | Each entry requires `id` and `reservationId`. Supports a deliberately configured party spanning linked bookings. |

Each watch requires a stable unique `id`, a `reservation`, and a `category`.
`name` is a human-readable label and defaults to `id`. Changing an ID, mode, account,
or sailing changes its notification identity. Changing the party resets identity only
in party mode. The state file stores a SHA-256 context key, product ID, last known
state, and notification acknowledgement; it does not store credentials or guest names.

To use availability alongside price checks in one instance, add the availability
section to an existing config with `only: false` (the default). Without that section,
upstream behavior is unchanged. `dryRun` controls only availability notifications;
normal price notifications and an explicit `appriseTest` retain upstream behavior.
For your separate instance, keep `only: true`.

## What the detector actually knows

Entertainment uses GraphQL category `show` and eligibility category `pt_show`.
Dining uses `dining` and `pt_dining`. Products are discovered through a complete,
paginated `WebProductsByCategory` query. Offerings and guest restrictions come from:

```text
POST /en/royal/web/commerce-api/eligibility/v1/eligibility
```

No cart addition, booking confirmation, cancellation, or purchase is performed.
The watcher does not call `/cart/v1/price`: your captured conflict and no-conflict
quotes differed only in offering IDs and did not validate inventory.

- Times are displayed as returned by Royal, without assuming a timezone conversion.
- `active: false` is not a booking gate. It appeared in both available and restricted
  captured responses.
- `stockLevel: 9999` is an API indicator, not a literal seat/table count. Even party
  mode does not promise that all guests will sit together at a restaurant.
- Each hard conflict is scoped to the offering ID. A guest's 7:15 PM conflict must
  not hide their 9:30 PM option.
- Party mode does not automatically suppress a dining watch just because the venue
  has already been booked. Railway returned remaining allowance of 9999 even for
  guests with an existing reservation. Disable the watch when no longer wanted, or
  use default one-time release alerts.
- Empty catalogs/offerings are different from unknown errors. HTTP errors, malformed
  JSON, GraphQL errors, incomplete pagination, and unrecognized eligibility evidence
  preserve prior state. Other products can still be checked after a product fails.
- A notifier must return success before the alert is acknowledged. Failed delivery
  retries on later checks. If a process dies after sending but before committing its
  acknowledgement, an alert can repeat. Partial success across multiple Apprise
  destinations can also repeat at successful destinations on retry.

## First live validation and cartId

Captured request bodies contained a `cartId`. The initial integration sends an empty
string and reuses the checker's authenticated session. Whether Royal accepts this has
not been verified live. If rejected, the result remains unknown; the script does not
create a cart or fabricate a token. A watch has an optional `cartId` override for
controlled local diagnosis, but an expiring captured browser cart ID is not a durable
production solution. Keep it out of source control.

Authentication interoperability, the reduced authenticated catalog query (including
Royal Railway discovery), and empty-cart behavior must be validated on your host.
A product absent from the complete catalog is considered not listed even if its
standalone detail URL remains accessible. Only Royal Caribbean is supported in this
initial availability extension.

## Verification and maintenance

Run the offline test suite with:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest unittests/ -q
```

`unittests/fixtures/availability` contains minimal anonymized fixture reductions.
The original uploaded captures and credentials are not included. The new GitHub
Actions workflow runs all tests, builds the Docker image, and exercises configuration
validation inside the image. On the `uberswimmer` fork, successful `main` builds
also publish the availability image to GHCR. Publication is pending the fork setup;
see `GITHUB-DEPLOYMENT.md`.

See `AVAILABILITY-REVIEW.md` for completed review, tests, and remaining validation.
See `UPSTREAM-BASELINE.md` for the exact upstream commit and fork maintenance approach.
