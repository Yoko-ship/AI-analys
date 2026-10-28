#!/usr/bin/env bash
# Receive a short-lived registry token on stdin; persist no registry credentials.
set -euo pipefail
image=${1:?image digest required}
expected_sha=${2:?commit required}
registry_user=${3:?registry user required}
[[ "$image" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || exit 2
[[ "$expected_sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
trap 'rm -rf "$DOCKER_CONFIG"' EXIT

# Keep the token in shell memory so each login attempt gets a fresh stdin.
IFS= read -r registry_token
registry_login() {
    printf '%s\n' "$registry_token" | docker login ghcr.io --username "$registry_user" --password-stdin >/dev/null
}
retry_registry() {
    local attempt status
    for attempt in 1 2 3; do
        if "$@" 2>"$DOCKER_CONFIG/registry-error"; then
            return 0
        else
            status=$?
        fi
        # Only transient transport errors qualify; authorization and invalid
        # manifests must fail immediately. Never print raw registry diagnostics
        # here: DNS errors can include private server/resolver addresses.
        if ! grep -Eqi 'i/o timeout|TLS handshake timeout|temporary failure in name resolution|connection reset by peer|connection timed out|network is unreachable|temporary failure|server misbehaving' "$DOCKER_CONFIG/registry-error"; then
            echo 'Registry request failed with a non-transient error.' >&2
            return "$status"
        fi
        if [[ "$attempt" == 3 ]]; then
            echo 'Registry connection failed after three attempts; the running release has not been stopped.' >&2
            return "$status"
        fi
        echo "Temporary registry connection failure; retrying in $((attempt * 5)) seconds." >&2
        sleep "$((attempt * 5))"
    done
}
retry_registry registry_login
unset registry_token
retry_registry docker pull "$image"
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
if [[ "$revision" != "$expected_sha" ]]; then
    echo 'The downloaded image does not match the tested commit.' >&2
    exit 1
fi
docker tag "$image" "uzstock-web:release-$expected_sha"
