# GitHub and Watchtower deployment

Docker image reference:

```text
ghcr.io/uberswimmer/royalcaribbean-availability:latest
```

Source is maintained at https://github.com/uberswimmer/CheckRoyalCaribbeanPrice.
The first AMD64/ARM64 publication succeeded on September 10, 2026:
https://github.com/uberswimmer/CheckRoyalCaribbeanPrice/actions/runs/34511737060

## GitHub publication and registry access

The `Availability build and publish` workflow runs the complete test suite, builds
and smoke-tests the native container, then publishes Linux AMD64 and ARM64 images
on successful `main` builds. ARM64 is built but not exercised by the native smoke
test. Manual runs on `main` also publish. Confirm the workflow succeeded before
the first pull.

Publishing uses the built-in `GITHUB_TOKEN` with `packages: write`, so no personal
access token is needed for Actions. The package name is separate from the inherited
upstream release workflow's image name.

New GHCR packages default to private. For pulls without credentials, open the
`royalcaribbean-availability` package under your GitHub profile's Packages tab,
then Package settings, and change its visibility to public. If you keep it private,
configure GHCR read access on both Docker and Watchtower. Do not commit registry
tokens, Royal credentials, or personal configuration.

## Start your separate container

Only one YAML configuration file is needed for this service. On the host it is
`config.availability.yaml`; the bind mount presents that same file inside the
container as `/app/config.yaml`. Do not create a second config inside the container.

Follow `AVAILABILITY-SETUP.md` to create `config.availability.yaml`, set your booking
IDs, and create the `data` directory. Match `TZ` and `CRON_SCHEDULE` to your existing
checker. Keep `only: true` and `dryRun: true` for the first diagnostic run.
After publication and registry access are confirmed:

```sh
docker compose -p royal-availability -f compose.watchtower.yaml pull
docker compose -p royal-availability -f compose.watchtower.yaml run --rm royal-availability check --validate-config
docker compose -p royal-availability -f compose.watchtower.yaml run --rm royal-availability check
```

Compare the dry-run output with Cruise Planner. Live authentication and empty-cart
eligibility requests still need verification. When correct, set `dryRun: false`:

```sh
docker compose -p royal-availability -f compose.watchtower.yaml up -d
```

The Compose file enables Watchtower's include label. If your existing Watchtower
uses explicit container names or a scope filter, add this new container to that
selection too. It must have pulling and restarting enabled, not monitor-only mode.
There is no new Watchtower instance or entertainment polling schedule.

## Future changes and rollback

Edit the fork through a branch and PR. Merging into `main` runs tests and publishes
an updated `latest` image. Your existing Watchtower can then pull it and recreate
the container on its configured schedule. It preserves the bind-mounted config and
`data` directory. Watchtower updates images; it does not apply changes to your local
Compose file, configuration, environment, or schedule.

Each publication also tags `sha-<full commit SHA>` for rollback. To stay on a known
version, replace `latest` in your local Compose file with that tag, then run `pull`
and `up -d`. Record the manifest digest from the workflow summary if you need an
exact immutable pin. Dependencies and the base image are unpinned, so rerunning a
workflow for the same source SHA may rebuild different bytes.

Upstream changes should be merged into a review branch and tested before merging
to your fork's `main`. A GitHub release alone does not update this availability
image; this workflow publishes successful `main` builds. Daily upstream monitoring prepares reviewed and tested update PRs. These PRs
require approval before merging; upstream changes are not automatically merged
into the deployed branch.

References:
- https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- https://containrrr.dev/watchtower/arguments/
