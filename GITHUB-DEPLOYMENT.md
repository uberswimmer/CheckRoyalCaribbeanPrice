# GitHub and Docker Compose deployment

The availability workflow publishes this image, using the repository owner's
lowercase GitHub username or organization name in place of `OWNER`:

```text
ghcr.io/OWNER/royalcaribbean-availability:latest
```

The `Availability build and publish` workflow runs tests and validates the native
container before publishing Linux AMD64 and ARM64 images on successful `main`
builds. ARM64 is built but is not exercised by the native smoke test. Manual runs
on `main` also publish. The workflow uses `GITHUB_TOKEN` with `packages: write`.
No personal access token is required for publication from Actions.

New GHCR packages default to private. For anonymous pulls, set the package's
visibility to public. Otherwise, configure registry read access on the Docker host
and any image updater. Keep registry tokens and personal configuration out of Git.

## Existing Docker Compose or Portainer stack

Use the image above in your existing stack. A separate updater-specific Compose
file is not required. The local-build `compose.availability.yaml` is an optional
example for development; it is not needed by an already deployed registry-image
stack.

Keep the existing timezone and cron schedule. Mount:

- Your host configuration file, read-only, at `/app/config.yaml`.
- A persistent host data directory at `/app/data`.

The host configuration may be named `config.availability.yaml`; it is the same
single file that appears inside the container as `/app/config.yaml`. Configure
`availability.stateFile: /app/data/reservation-availability-v2.json` to retain alert
history across container recreation.

The reservation-centric build uses a different state identity from the older
watch-scoped JSON and earlier SQLite builds. Use the new v2 path and expect one
fresh alert for products already available. Leave old state files in place as
backups; do not rename them into the v2 path. See
[AVAILABILITY-SETUP.md](AVAILABILITY-SETUP.md#state-migration).

Initially use `only: true` and `dryRun: true`. In the container console, validate
configuration and then perform one live diagnostic check:

```sh
./entrypoint.sh check --validate-config
./entrypoint.sh check
```

Compare results with Cruise Planner before enabling notifications with
`availability.dryRun: false`. Combined mode (`only: false`) still sends normal
price alerts even when availability dry run is enabled.

## Updates and rollback

Successful application builds on `main` update `latest`. Pull the new image and
recreate the service through the existing stack or configured image updater.
Restarting alone does not download an image. Preserve configuration and data mounts.
An image update does not apply edits to the host Compose file or configuration.

The workflow also publishes `sha-<full commit SHA>` tags. To roll back, set the
stack's image to a known-working tag, pull, and recreate. Use the manifest digest
from the workflow summary for an immutable pin, since rerunning the same source
commit can change unpinned dependencies or base-image contents.

Review upstream changes in a separate branch before merging them into `main`.
The availability workflow publishes from `main`, independently of the inherited
upstream release workflow and its different package name.
