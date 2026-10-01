# Upstream baseline and contribution workflow

- Upstream: https://github.com/jdeath/CheckRoyalCaribbeanPrice
- Integrated upstream commit: `4c10b818b860ae9d2bad9de614ebbe66c0a4d182`.
- Commit: Merge pull request #146, per-account `casinoOffersOnly` support.
- Previous common ancestor: `5d6185f1e81fb60569c079b7fe8d379d64867079`.
- Latest published upstream release when integrated: `3.6.0`. The baseline above
  includes subsequent upstream commits, not just that release.
- License: upstream MIT license retained in `LICENSE`.

## Ownership

Upstream owns pricing, cabin availability, upgrades, Club Royale, notification
routing, and the complete `reservationAlerts` implementation, including config,
request pacing, validation, aggregation and readable v2 JSON notification state.
There is no second reservation-alert subsystem or dedicated alert-only run mode.

The fork retains local calendar/activity capture and its preservation safeguards,
HTML/plain-text reports, Docker run controls, configuration-only validation, and
checker/report image publication. Its small Windows-encoded configuration fallback
remains covered by a regression test. Calendar identifiers and saved event identities
are preserved; upstream's reservation-state migration does not reset calendar data.

Keep upstream's single-file checker layout and public interfaces. Coordinate larger
changes with [upstream issue #140](https://github.com/jdeath/CheckRoyalCaribbeanPrice/issues/140).
The inherited browser/phone/casino tools, packaging files and platform tests remain.

## Contributions and synchronization

1. Keep deployed fork features on fork `main`.
2. Branch upstream contributions from current **upstream main**.
3. Bring over only the focused feature and tests intended for upstream.
4. Keep Docker, report hosting and GHCR changes out of upstream submissions.
5. After acceptance, merge current upstream into an isolated fork review branch,
   retain real upstream ancestry, and remove superseded fork implementations.
6. Review the final fork-versus-upstream diff, run all tests, and use a normal merge
   for the integration PR so upstream history remains visible.

PR #11 remains separate. Port its onboard-activity support onto upstream's category
model only after this integration has been merged and validated on the host.

## Validation and deployment

Retain upstream's Python 3.11 minimum/latest Apprise test matrix and the fork's
Python 3.12 Docker/browser workflow. Inherited release YAML files remain for parity;
unused release workflows can be disabled in this fork's Actions settings.

Main publishes the existing checker/report images automatically. Follow
[the deployment and rollback checklist](LOCAL-WEB-SETUP.md#migration-from-the-pre-upstream-fork)
before merging a configuration/state transition. Never equate published images with
verified deployment on the Docker host. Dependencies/base images remain unpinned;
record a known-good image digest before updating.
