#!/bin/sh
set -eu

# Railway volumes and VPS bind mounts can both replace /app/data after the image
# is built.  The application runs as appuser, so make this one fixed runtime
# location writable before dropping privileges.  Do not chown arbitrary
# environment-controlled paths.
mkdir -p /app/data
chown -R appuser:appuser /app/data

# The Claude gateway keeps its subscription login in its own volume; the CLI must
# be able to refresh it in place. Only this fixed path is ever prepared.
if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
    case "$CLAUDE_CONFIG_DIR" in
        /app/claude-home)
            mkdir -p "$CLAUDE_CONFIG_DIR"
            chown -R appuser:appuser "$CLAUDE_CONFIG_DIR"
            chmod 700 "$CLAUDE_CONFIG_DIR"
            ;;
        *)
            echo "Unsupported CLAUDE_CONFIG_DIR path: $CLAUDE_CONFIG_DIR" >&2
            exit 64
            ;;
    esac
fi

exec gosu appuser "$@"
