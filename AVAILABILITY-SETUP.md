# Royal Caribbean availability test build 0.1.0

This source build adds entertainment and dining availability monitoring directly to
`CheckRoyalCaribbeanPrice.py`. It does not run or import the Browse script. It uses
the checker's existing authentication, request helper, and Apprise notifications.

The supplied Compose configuration creates a separate service and image. It defaults
to availability-only operation, so it does not duplicate cabin/add-on price alerts.
It uses the existing upstream Dockerfile and scheduler. No additional polling loop
or entertainment-specific schedule is added.

For GitHub-published images and an existing Docker Compose or Portainer deployment,
see [GITHUB-DEPLOYMENT.md](GITHUB-DEPLOYMENT.md).
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
   sailing.
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
failed or insufficient evidence, not closed reservations. A failed availability check exits nonzero
in either mode. Combined mode completes price summaries and exports before reporting
the availability failure. Fix failures before relying on monitoring.

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

In combined mode, the `Reservation Availability Watches` console section runs
after booked-item price watches and the prospective cruise watchlist, before the
check-in/payment summary. It reuses each account's existing authenticated session
and booking snapshot. Availability-only mode uses the same section layout.
Blue headings separate accounts and watches; available results are green,
unavailable results yellow, and unknown/error results red. Times are grouped by
date in 24-hour format, preserving the wall-clock times returned by Royal.

`availability.dryRun` is not a global dry-run switch. The upstream program has no
general dry-run mode: combined price checks can still send their normal alerts.
The console labels this setting as `Availability dry run` to make the scope clear.

## What the detector actually knows

Entertainment uses GraphQL category `show` and eligibility category `pt_show`.
Dining uses `dining` and `pt_dining`. Products are discovered through a complete,
paginated `WebProductsByCategory` query. Offerings and guest restrictions come from:

```text
POST /en/royal/web/commerce-api/eligibility/v1/eligibility
```

Royal's entertainment catalog can also contain products in other categories, such
as escape-room experiences. Automatic show discovery logs and skips products with
an explicit different `pt_` category; these do not cause a failed check or a show
release alert. A missing/malformed type remains unknown, and an explicitly watched
product with a category mismatch still reports an error. Skipping a product does
not clear its existing notification history. This watcher does not monitor escape
room availability.

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

## State location and diagnostics

Relative `availability.stateFile` paths use the process's working directory, as in
previous extension versions. Use an absolute path to keep notification history in
the same location when launching from different directories. For Docker, use
`/app/data/availability.sqlite3` and keep `/app/data` bind-mounted. On other systems,
choose an explicit writable absolute path. No path migration or automatic database
movement is performed.

Configuration errors name their location, for example
`availability.watches[1].guests[0]`, and identify an invalid key without printing its
value. List indexes start at zero. Missing booking numbers are assessed across all
successfully retrieved accounts in both modes. A failed API lookup is not interpreted
as a known unavailable product.

Expected availability failures print concise diagnostics and exit nonzero without a
Python traceback. `notifyOnError` continues to control the existing global error
notification. Unexpected programming errors retain tracebacks. No notification
service, failed delivery, and state-storage problems have distinct messages; an alert
is never acknowledged until delivery is confirmed.

Catalogs are reused only for watches with the same account, booking, and category
within a single pass. Failed catalog results are also reused within that pass to
avoid repeating the same failed request sequence. Each later run fetches fresh data.
Eligibility queries are not cached and still use each watch's own party.

Notification identity continues to include the account. If the same booking is
visible to two configured accounts, both can notify. To avoid that today, run
availability with a configuration containing one account that can see the intended
bookings. There is no new implicit account-selection or cross-account deduplication
policy in this update.

## First live validation and cartId

Live entertainment checks have succeeded using the checker's authentication and
default empty `cartId`, including examples with listed inventory and no listed shows.
This is evidence for those tested scenarios, not a guarantee for every account,
sailing, or dining product. Royal Railway and party-aware checks still need live
validation through the checker.

If Royal rejects the empty cart ID, the result stays unknown; the script does not
create a cart or fabricate a token. The optional per-watch `cartId` is for controlled
local diagnosis. An expiring browser cart ID is not a durable production solution
and must not be committed to source control.

Compare returned inventory with Cruise Planner before relying on a new watch. A
product absent from the complete catalog is considered not listed even if its
standalone detail URL remains accessible. Only Royal Caribbean is supported in
this initial availability extension.

## Verification and maintenance

Run the offline test suite with:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest unittests/ -q
```

`unittests/fixtures/availability` contains minimal anonymized fixture reductions.
The original uploaded captures and credentials are not included. The new GitHub
Actions workflow runs all tests, builds the Docker image, and exercises configuration
validation inside the image. Successful `main` builds
also publish the availability image to GHCR. The publishing workflow derives the image owner from the repository;
see `GITHUB-DEPLOYMENT.md` for registry access and first-run instructions.

See `AVAILABILITY-REVIEW.md` for completed review, tests, and remaining validation.
See `UPSTREAM-BASELINE.md` for the exact upstream commit and fork maintenance approach.
