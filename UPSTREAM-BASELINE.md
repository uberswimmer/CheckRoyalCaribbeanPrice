# Upstream baseline

- Repository: https://github.com/jdeath/CheckRoyalCaribbeanPrice
- Baseline commit: `8cfd8f769da725d940ea83e89f51a4d22a869c45`
- Commit subject: Merge pull request #114 from AESternberg/main
- Local development branch: `feature/availability-watches`
- Extension version: `0.1.0-test`
- License: upstream MIT license retained in `LICENSE`.

This build starts from the inspected upstream main commit, not an inferred container
release or moving `latest` tag. See `GITHUB-DEPLOYMENT.md` for the publishing
workflow and dedicated GHCR image. The registry owner is derived from the repository
at build time; no personal account name is configured in source.

In the fork, use `main` for the availability extension and merge upstream into
a review branch first. Fetch upstream changes, merge them into the extension branch in a reviewable
PR, run the complete test suite and Docker smoke test, then compare live diagnostics
before replacing the container. Preserve the bind-mounted availability state file.

The extension stays in `CheckRoyalCaribbeanPrice.py`, as requested. Integration hooks
are limited to configuration, the existing booking pass, and the availability-only
main branch. There is no new scheduler or Browse subprocess. The separate
`availability.watches` configuration avoids changing the price watchlist's required
fields or alert semantics.

Direct dependencies tested locally with Python 3.12.14:

- requests 2.34.2
- PyYAML 6.0.3
- Apprise 1.13.1
- curl_cffi 0.16.3
- pytest 9.1.1

The upstream Docker base and requirements remain unpinned; dependency versions and
the Python Alpine base can change on a future rebuild. Preserve your known-working
image tag/digest when moving beyond the test stage. Review and test upstream update PRs before merging into the deployed branch.
