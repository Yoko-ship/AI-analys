# Telegram pull request review

GitHub sends a webhook when CI completes on a pull request. The local review
listener verifies the signature, checks the run against the current pull
request, and invokes the reviewer after the required jobs pass. Eligible
Telegram drafts can then merge through the UZStock PR Review GitHub App.

The listener and its Cloudflare connector start when the Windows user signs
in. If a delivery fails while the PC is offline, the listener checks open
pull requests when it starts. For a failed delivery while the PC is running,
redeliver the GitHub webhook or rerun the pull request checks.
