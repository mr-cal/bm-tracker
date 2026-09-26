# agents.md

## Before completing any task

Before completing any task, run and ensure the following pass:

```bash
make format
make lint
make test
```

Existing failures should be noted and communicated to the user.

Any changes to the Dockerfile or Alembic migrations should also verify that
`make build` succeeds.

Finally, your changes should be committed and pushed to github. Then, you must wait
for the image to successfully build, for `mr-cal/vps-infra` to successfully deploy,
and then verify your changes are on the production website.

## Before completing UI/UX tasks

Run the e2e tests when making UI or UX changes:

```bash
make test-e2e  # ~5-10 min
```

## Verification and deployment

The VPS for this project is managed by the `mr-cal/vps-infra` repo on github.
When you push to `mr-cal/bm-tracker`, the vps-infra will pick up the newly made changes.

Don't change the configured git url for origin when pushing and pulling changes.
Instead, just push to a custom url with the token.

There is no local dev website. For example, you shouldn't create a local Docker
instance and set up a local website for testing.

## Image publishing

Pushing to `main` triggers `.github/workflows/publish.yml`, which builds and
pushes `ghcr.io/mr-cal/bm-tracker:latest` to GHCR, then dispatches a
`repository_dispatch` event to [mr-cal/vps-infra](https://github.com/mr-cal/vps-infra)
to trigger a redeploy. The vps-infra deploy workflow pulls the new image and restarts
the container. You should verify the deployment job succeeded after pushing commits.

A `VPSINFRA_PAT` secret must be set on this repo (Settings → Secrets and variables →
Actions) with a fine-grained PAT scoped to `mr-cal/vps-infra` with
**Contents: Read and write**.
