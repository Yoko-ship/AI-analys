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

# Fix the cause, not the case

When fixing something, fix the general cause so the same kind of problem cannot
come back, not just the one instance that was reported. Ask why the case slipped
through and change the rule, check or data flow that let it through, so that
every future case of the same shape is handled too. Avoid hardcoding the
reported ticker, filing, source or value as a special case. Where the fix rests
on a threshold or heuristic, check it against real data, both the cases it
should catch and the ones it must not, and cover both with tests.
