# agents.md

## Before completing any task

Before completing any task, run and ensure the following pass:

```bash
make format
make lint
make test
```

`make lint` runs ruff, `ty` and gitleaks.

Existing failures should be noted and communicated to the user.

Any changes to the Dockerfile or Alembic migrations should also verify that
`make build` succeeds.

## Local development comes first

Do not deploy until phases 0-8 are done and the user has tested the app locally
and said it is right. See `plans/plan-01-bootstrapping.md` section 10.

To run the app locally with a real database:

```bash
make setup
make dev-reset   # fresh DB, migrations applied, prints admin credentials
make dev         # http://127.0.0.1:8000
```

Use `make dev-seed` instead of `make dev-reset` to populate it with fake users
and history. The local database is `./data/bm_tracker.db`.

Commits and pushes are welcome during development, but do not make vps-infra
changes or trigger a deploy without being asked. Once a change is signed off
locally, the agent pushes and waits for the image build, for `mr-cal/vps-infra`
to deploy, and then verifies the change on the production site.


## Before completing UI/UX tasks

Run the e2e tests when making UI or UX changes:

```bash
make test-e2e  # ~5-10 min
```

These drive Puppeteer against the app running in-process on an ephemeral port
with a temporary SQLite database seeded by `make seed-e2e`. There is no
SQL-executing seed endpoint in this app, deliberately — do not add one.

## Verification and deployment

The VPS for this project is managed by the `mr-cal/vps-infra` repo on github.
When you push to `mr-cal/bm-tracker`, the vps-infra will pick up the newly made changes.

Don't change the configured git url for origin when pushing and pulling changes.
Instead, just push to a custom url with the token.

To push without stored credentials, mint a token with
scripts/mint_bot_token.py from mr-cal/vps-infra (see its
docs/github-app-auth.md) and the GitHub App creds in .env.llm;
the script caches tokens in .local/ two levels above itself, so
keep it somewhere writable:

git push "$(uv run mint_bot_token.py --print-remote-url)" main

The production site is **https://3142468.xyz**. It must not be exposed or
referenced until the local testing handover is signed off.

## Image publishing

Pushing to `main` triggers `.github/workflows/publish.yml`, which builds and
pushes `ghcr.io/mr-cal/bm-tracker:latest` to GHCR, then dispatches a
`repository_dispatch` event to [mr-cal/vps-infra](https://github.com/mr-cal/vps-infra)
to trigger a redeploy. The vps-infra deploy workflow pulls the new image and restarts
the container. You should verify the deployment job succeeded after pushing commits.

A `VPSINFRA_PAT` secret must be set on this repo (Settings → Secrets and variables →
Actions) with a fine-grained PAT scoped to `mr-cal/vps-infra` with
**Contents: Read and write**.
