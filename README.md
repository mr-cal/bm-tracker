# bm-tracker

A private, mobile-first daily bowel-movement tracker. A small group of
admin-provisioned users logs their daily bowel movements; points and streaks
reward logging at the moment it happens; achievements and a group feed sit on
top.

Invites only. Deployed to the same VPS as craft-dashboard.

## Development

```bash
make setup      # install dependencies and the pre-commit hooks
make dev-seed   # rebuild ./data/bm_tracker.db with 8 fake users and two years
                # of history, all with the password e2e-password
make dev        # http://127.0.0.1:8000
```

`make dev-reset` gives the same database with an empty schema instead, for
working on a page that has no data behind it yet.

The seed is deterministic: the same `--seed` and `--users` produce the same
history, which is what lets the e2e suite assert on it.

Then, before any commit:

```bash
make format
make lint
make test
```

`make lint` runs ruff, `ty` and gitleaks. gitleaks is a separate binary and
must be installed — see the target for details.

## Documentation

`plans/plan-01-bootstrapping.md` is the build specification: the data model and
scoring rules, the code layout, the test plan, and the deployment wiring. It is
git-ignored and therefore local-only.
