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

docker login ghcr.io --username "$registry_user" --password-stdin >/dev/null
docker pull "$image"
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
if [[ "$revision" != "$expected_sha" ]]; then
    echo 'The downloaded image does not match the tested commit.' >&2
    exit 1
fi
docker tag "$image" "uzstock-web:release-$expected_sha"
