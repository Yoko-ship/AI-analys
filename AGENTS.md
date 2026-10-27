# Deployment target

This project is deployed to the `uzstock.uz` server, not Railway.

The SSH connection details are private and live only in the local, git-ignored
`.env` file (see `.env.example`):

- `DEPLOY_SSH_HOST`
- `DEPLOY_SSH_PORT`
- `DEPLOY_SSH_USER`

Never write the host address, port, user, passwords or keys into tracked files.

Before a production deployment, inspect the active application directory and
service manager on this host. Do not use Railway deployment or recovery tools.

# Tests first

Write the test before the code. For a bug, first add a test that reproduces it
with the real case (the ticker, filing or value that went wrong) and run it to
see it fail; for a feature, first write a test that states the expected
behaviour. Only then change the code, and finish when that test and the full
suite (`.venv/bin/python -m pytest -q`) pass.

A test that never failed proves nothing: if the fix is already in place, check
the test against the unfixed code before relying on it.

Before adding a test, look for existing coverage of the same behavior and extend
it where appropriate. Keep distinct real regressions and boundary cases, but do
not copy the same inputs and assertions into another module. For mocked I/O,
simulate pacing and retry clocks instead of sleeping in real time, and assert
the requested delays. CI should run each backend case once per Python version;
targeted development runs need not be repeated alongside the full suite in CI.

# Browser checks during feature implementation

Run browser tests for the feature being implemented before declaring it done,
not automatically on push or pull request. For a UI feature or bug, first add
or update the relevant Playwright regression and observe it fail against the
unimplemented or unfixed behavior. After the change, build the current frontend
and run the relevant spec files:

```sh
npm run build
npm run test:e2e -- e2e/<feature>.spec.js
```

Replace the placeholder with actual spec paths; pass multiple paths when shared
components affect more than one feature. Rebuild before each browser check after
changing frontend code, because Playwright tests the built app. Install Chromium
with `npx playwright install chromium` once if it is missing (on Linux, use
`npx playwright install --with-deps chromium` for its system dependencies).

Report which feature specs ran and their results when finishing the work. The
full browser suite remains available manually with `npm run test:e2e` after a
build, but is not a push or deployment prerequisite. CI still runs backend tests,
frontend unit tests, lint and builds, and the targeted live market smoke checks
still run after production deployment.

# Fix the cause, not the case

When fixing something, fix the general cause so the same kind of problem cannot
come back, not just the one instance that was reported. Ask why the case slipped
through and change the rule, check or data flow that let it through, so that
every future case of the same shape is handled too. Avoid hardcoding the
reported ticker, filing, source or value as a special case. Where the fix rests
on a threshold or heuristic, check it against real data, both the cases it
should catch and the ones it must not, and cover both with tests.
