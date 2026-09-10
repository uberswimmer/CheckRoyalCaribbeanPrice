# GitHub and Watchtower deployment

Prepared image reference:

```text
ghcr.io/uberswimmer/royalcaribbean-availability:latest
```

**Publication is pending.** This address is not verified as pullable. The current
source has not yet been pushed to an accessible GitHub fork. Do not change your
running container until the first successful publication is confirmed.

## One-time GitHub setup

1. Fork https://github.com/jdeath/CheckRoyalCaribbeanPrice into `uberswimmer`.
   Keep the repository name `CheckRoyalCaribbeanPrice` and default branch `main`.
2. Allow the connected GitHub app to access the fork if it uses selected repositories.
3. Enable GitHub Actions on the fork's Actions tab. The extension source and its
   publishing workflow must then be committed to the fork's `main` branch.
4. The `Availability build and publish` workflow tests the code and smoke-tests the
   native container before publishing Linux AMD64 and ARM64 images. ARM64 is built
   but not exercised by the native smoke test. A failed test/build prevents the
   publishing job or image export. Manual runs on `main` also publish.
5. After the first publication, open the `royalcaribbean-availability` package under
   your GitHub profile's Packages tab. For pulls without credentials, change its
   visibility to public in Package settings. New GHCR packages default to private.
   If you keep it private, configure GHCR read access on both Docker and Watchtower.
   Do not commit registry tokens, Royal credentials, or personal configuration.

Publishing uses the workflow's built-in `GITHUB_TOKEN` with `packages: write`.
No personal access token is needed to publish from Actions. The package name is
separate from the inherited upstream release workflow's image name.

## Start your separate container

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
image; this workflow publishes successful `main` builds. No automatic upstream
merge task has been configured.

References:
- https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- https://containrrr.dev/watchtower/arguments/
