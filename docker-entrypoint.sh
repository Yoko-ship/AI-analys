#!/bin/sh
set -eu

# Railway mounts volumes after the image is built, usually as root. Codex must be able
# to refresh auth.json in place, so prepare only the two explicitly supported auth paths
# before dropping privileges. No other environment-controlled path is ever chowned.
if [ -n "${CODEX_HOME:-}" ]; then
    case "$CODEX_HOME" in
        /home/appuser/.codex|/app/data/codex-home)
            mkdir -p "$CODEX_HOME"
            if [ ! -s "$CODEX_HOME/auth.json" ] && [ -n "${CODEX_AUTH_JSON_B64:-}" ]; then
                (umask 077
                 printf '%s' "$CODEX_AUTH_JSON_B64" | base64 -d > "$CODEX_HOME/auth.json.seed")
                mv "$CODEX_HOME/auth.json.seed" "$CODEX_HOME/auth.json"
            fi
            chown -R appuser:appuser "$CODEX_HOME"
            chmod 700 "$CODEX_HOME"
            ;;
        *)
            echo "Unsupported CODEX_HOME path: $CODEX_HOME" >&2
            exit 64
            ;;
    esac
fi

# The model subprocess also receives an explicit environment allowlist, but remove the
# one-time seed before the application starts so it cannot leak through unrelated children.
unset CODEX_AUTH_JSON_B64
exec gosu appuser "$@"
