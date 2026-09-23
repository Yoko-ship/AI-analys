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
