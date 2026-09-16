# Availability build review

## Result

The 0.1.0-test source build is complete and ready for a diagnostic run in a separate
container. Review and offline validation passed. GitHub Actions also passed the
native Docker build, Compose validation, and container configuration/entrypoint
smoke test on September 10, 2026. Live entertainment discovery has since been confirmed. Dining, party restrictions,
and notification persistence across container recreation still require host validation.
This is a test build, not a claim of production or booking success.

## Scope reviewed

- Opt-in configuration and unchanged default price-check behavior.
- Availability-only orchestration and shared account authentication.
- Catalog discovery, pagination, typed absence, and eligibility requests.
- Release versus party evaluation, including per-offering conflict handling.
- Persistent notification acknowledgement, failed delivery, and concurrency.
- Separate-container settings, bind mounts, command forwarding, and setup guide.
- Anonymized fixtures and exclusion of credentials/original captures from the bundle.

The review was performed after the initial implementation by re-reading the modified
paths and exercising captured cases, malformed responses, and failure scenarios.

## Corrections made during review

1. **Malformed nested API data:** added an evaluation boundary that returns unknown
   for malformed objects rather than crashing or treating missing values as availability.
2. **Sailing isolation:** reject eligibility offerings outside the requested voyage;
   a matching product code alone is insufficient because codes can recur across sailings.
3. **Account isolation:** upstream login exits on failure. Availability-only mode now
   catches that failure, continues remaining accounts, and reports a failed overall run.
4. **Configuration mistakes:** reject ambiguous string booleans, unknown availability
   keys, duplicate watch IDs, missing dining product codes, invalid guest lists, and
   availability-only configurations without supported accounts.
5. **State identity:** release notification identity is independent of party composition;
   party mode includes the guest list. Changing a party cannot re-alert a release watch.
6. **Inventory errors:** failed HTTP/GraphQL responses and incomplete pagination stay
   unknown. Numeric zero with an explicit sold-out status is unavailable; a missing
   or unknown stock field cannot silently re-arm an alert.
7. **Notification failures:** only a true success result from Apprise acknowledges an
   alert. Missing notifier, false/None result, or exceptions leave delivery retryable.
8. **Container commands:** the `check` entrypoint now forwards arguments, allowing
   `check --validate-config` inside the same image. The sample starts in dry-run mode.

## Verification completed

- Upstream baseline: **234 tests passed** before availability implementation.
- Final combined suite: **311 tests passed**, including **77 availability tests**.
- Python syntax compilation passed.
- Shell syntax validation passed for `entrypoint.sh`.
- YAML parsing passed for the sample configuration, Compose file, and new CI workflow.
- `git diff --check` passed.
- Privacy scan of fixture reductions against private values in the source captures passed.

The final test run used Python 3.12.14. One warning was also present in the upstream
baseline suite; no test failed. Configuration validation was exercised in a separate
Python process. An end-to-end availability-only test routes synthetic booking data,
the reduced captured catalog, and the captured Headliner eligibility response through
the production functions, then verifies one alert across two runs.

| Case | Verified behavior |
| --- | --- |
| Wonder catalog | Typed `CommerceProductNotFound` is treated as no listed products. |
| Elemental | Release detected; party blocked by exhausted booking allowance. |
| Headliner | Party mode retains 21:30 and excludes the 19:15 conflict. |
| Royal Railway | Party mode retains the four offerings without reported conflicts. |
| Existing reservation | Does not suppress release-mode detection. |
| Catalog pagination failure | No fabricated absence or state re-arming. |
| First available result | One alert, including availability already present on first live run. |
| Restart / concurrent checks | Successful acknowledgements prevent duplicate decisions. |
| Failed notification | Retried on a subsequent scheduled check. |
| Unknown after available | Previous state and acknowledgement preserved. |
| Reopening | Alerts again only with `notifyOnReopen: true` after known unavailability. |
| Dry run | No availability notification or state creation/advancement. |
| Availability-only | Does not call the price/profile/ship-discovery paths. |
| Default configuration | Existing upstream tests continue to pass. |

## Remaining live checks

1. Authenticate in your separate instance with your existing Royal credentials.
2. Confirm the reduced authenticated catalog query returns the intended shows and
   `UT_RAILDINNER` for your actual bookings.
3. Confirm eligibility accepts the empty `cartId`. If it does not, diagnose session/cart
   context before enabling alerts. The code deliberately does not create carts.
4. Compare returned times and restrictions with Cruise Planner in dry-run mode.
5. Enable alerts and confirm a first live notification using your configured Apprise
   destination. Preserve `data/availability.sqlite3` when replacing the container.

The build workspace has no Docker daemon. Remote validation is now available:
the repository's Actions tab, `Availability build and publish` workflow.
The `test` job passed the suite, native image build, the local-build Compose configuration,
and `check --validate-config` inside the image. This does not verify a live login,
API call, notification, cron execution, or ARM64 runtime behavior.

Royal Railway's `9999` stock signal is not interpreted as a literal seat count or
proof of a table for seven. These captures validate reported inventory and restrictions,
not checkout. The watcher does not reserve, purchase, modify, or cancel anything.

## Upstream-readiness refinements

The proposed readiness change addresses combined-mode failure propagation,
configuration diagnostics and per-run catalog reuse. Price
summaries and JSON exports finish before an availability failure marks the run as
failed. Expected availability failures preserve the existing error notification
and nonzero exit behavior without a traceback; programming errors retain theirs.

The review specifically checks that caches do not cross accounts or runs, that
eligibility remains per-watch, and that a failed check does not skip later accounts.
State paths retain their existing working-directory-relative behavior; use an absolute
path for a stable location. No path migration or account-deduplication policy is
introduced. The existing absolute Docker state path is unaffected. The command-line
handler is a directly testable function, without source parsing in the tests.

Live entertainment discovery is now confirmed by user-provided console results.
The mixed-catalog tests include the observed `pt_onboardActivities` category.
Remaining host validation: actual notification receipt, suppression of repeats
across reruns and container recreation, and live dining/party-aware scenarios.
An upstream submission still needs the maintainer's configuration-design preference
and a contribution branch excluding fork-specific deployment material.

Local verification of the readiness changes: **346 tests passed**, including
18 additional regression cases, with the same existing dependency deprecation warning.
Remote Python and container validation results are recorded on the refinement PR.

## Upstream 3.6.0 sync review

Upstream `main` through `613e6880606ab138c1b1d560322e59d74ad5eadf` was
merged into the fork on a review branch. This includes release `3.6.0` plus its
two subsequent `.DS_Store` cleanup commits. The only content conflict was the
end-of-run boundary in `CheckRoyalCaribbeanPrice.py`; the resolution preserves
calendar export completion, availability failure propagation, upstream's
distinct partial-account failure exit, and final price-history status.

Review also found that a successful login followed by a failed profile request
could leave its session outside both existing cleanup paths. The merged code now
closes that session, with a regression assertion covering the profile-failure
path.

Local validation: **442 tests passed**, Python and shell syntax checks passed,
YAML parsing passed, and `git diff --check` passed. The local environment did not
provide a Docker daemon or CLI. The pull request's GitHub Actions run subsequently
passed the native image build, Compose validation, container entrypoint/configuration
check, report-image build, and report-server smoke test on September 13, 2026.

## Upstream loyalty-night routing sync review

Upstream `main` through `7dbd6cb9332c5934caa7ba11060f40a15c7904dd` was
merged into the fork on a review branch. The change routes Crown & Anchor and
Captain's Club history lookups by the loyalty program being queried instead of the
login brand, preventing cross-brand profiles from querying the wrong endpoint.

The merge applied cleanly. Availability monitoring, scheduled checks,
configuration compatibility, persistent notification state, scoped price-alert
exclusions, and the dedicated GHCR workflow are unchanged. No configuration or
state migration is required.

## Upstream cabin-subtype and final-payment sync review

Upstream `main` through `eaaf68fe9a80cda2a455a88305fcd81f33862962` was merged on an isolated review branch. Git merged the source and tests cleanly. Review verifies that Royal's renamed funnel subtype-code fallback coexists with the fork's tri-state cabin-inventory result, and that the best-price path now displays an expired final-payment date. Entertainment/dining availability orchestration, scheduled checks, persistent notification state, configuration compatibility, calendar/report exports, and the dedicated GHCR workflow are unchanged. No configuration or state migration is required.
