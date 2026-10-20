# GHCR releases

## Promote and tag

Develop on `feature/*` branches and merge reviewed pull requests into `dev`.
Promote a tested `dev` change to `main` through a separate reviewed pull request.
The release workflow accepts only annotated tags matching `vMAJOR.MINOR.PATCH`
(for example, `v1.2.3`). Prerelease and build metadata are not supported.

Create a release only after `main` contains the approved change and its four CI
checks pass. This initial policy requires the tag to point to the exact current
`origin/main` HEAD both at initial validation and again immediately before
publishing:

```sh
git switch main
git pull --ff-only origin main
git tag -a v1.2.3 -m "NamiCash v1.2.3"
git push origin v1.2.3
```

Protect the `v*` tag namespace in GitHub so only release maintainers can create
tags and existing tags cannot be updated or deleted. The workflow never creates
or increments tags. A push to `dev` or `main`, a pull request, or an arbitrary
non-SemVer tag does not publish images.

## Build and verify

`.github/workflows/release.yml` runs only for pushed tags beginning with `v`.
It verifies strict SemVer syntax, requires an annotated Git tag, fetches current
`origin/main`, and requires the tag commit, checked-out commit, and main HEAD to
match. After both images build and pass local smoke tests, it repeats the main
HEAD check before authenticating and publishing. It uses GitHub-hosted Ubuntu
runners and `GITHUB_TOKEN` with package write permission. It builds and publishes
`linux/amd64` backend and frontend production images to GHCR. No deployment,
migration, or production credential is involved.

For `v1.0.0`, each image receives `v1.0.0` and `sha-<full-40-character-commit>`
tags. Both tags are generated from the validated release version and peeled tag
commit. The workflow applies OCI source, version (including the `v` prefix),
revision, and creation-time labels. Before either image is pushed, the backend
image is checked for imports, Alembic files, and required scripts. The frontend
production image is checked for static assets and its real Nginx configuration
on an isolated Docker network with a temporary backend DNS alias. Both
published digests are then pulled back from GHCR and verified for `amd64` and
expected contents. Only after both images pass does the workflow attach
`release-manifest.json` to the Actions run as the
`release-manifest-<version>` artifact. The workflow summary includes the same
manifest.

Prefer digest references for verification and deployment, for example:

```text
ghcr.io/mafunamiii/namicash-backend@sha256:<manifest-backend-digest>
ghcr.io/mafunamiii/namicash-frontend@sha256:<manifest-frontend-digest>
```

Compare the manifest's `source_commit` with `git rev-parse v1.2.3^{commit}` and
the recorded commit in the main history. Confirm the two digests and workflow run
URL in the artifact/summary. A digest is the immutable image identity. Version
and SHA tags are convenience pointers; always verify the manifest digest and do
not use a mutable tag as the production deployment reference.

## Failure recovery

Publishing two separate GHCR packages is not atomic. If one image publishes and
the other fails, the workflow fails and does not upload a release manifest.
Treat the release as incomplete: do not deploy either image. Inspect the failed
run, package tags, and published digests; correct the cause, then use **Re-run
all jobs** on that workflow run. Do not create another version tag for the same
release. The rerun rebuilds and tests both exact-commit images before publishing
again. Only use image digests recorded in the successful manifest; treat any
partial or orphaned image as unpublished.

The two main-HEAD checks narrow but cannot eliminate a race: `main` could advance
after the final check and before or during the registry pushes. The release
policy is not relaxed; for the initial process, avoid merging to `main` while a
release run is publishing, and confirm the manifest commit still matches the
intended release commit.

## GHCR access and deployment boundary

Before the first release, confirm the package's repository link and Actions write
access using [GitHub's package access settings](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).
The workflow applies `org.opencontainers.image.source` so GHCR can associate the
package with this repository. Configure access to inherit
repository permissions where available. Set visibility to public only if public
image pulls are intended; otherwise keep it private and grant the homeserver's
future read-only pull identity explicit package access. GHCR creates new packages
as private by default. The workflow uses the repository `GITHUB_TOKEN`; no
personal access token is required.

Image publishing is not production deployment. Merging into `main` does not run
this workflow; only a manually created release tag does. Publishing does not
authorize image rollout, alter Compose configuration, access production data,
or restart services. A later deployment phase must define its own approval.

An optional future mirror may copy verified GHCR digests to the homeserver's
Tailscale-bound Docker Distribution v2 registry at `100.93.39.106:5000`. That
registry is not read or modified by this workflow.
