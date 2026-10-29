#!/usr/bin/env bash
# Publish the already smoke-tested image; use the registry digest from this push.
set -euo pipefail
image_tag=${IMAGE_TAG:?image tag required}
[[ "$image_tag" =~ ^ghcr\.io/[a-z0-9._/-]+:[a-f0-9]{40}$ ]] || exit 2
: "${GITHUB_OUTPUT:?workflow output file required}"

push_output=$(docker push "$image_tag")
printf '%s\n' "$push_output"
# RepoDigests is local metadata: the image also has a local smoke-test alias,
# and the first entry need not identify the repository just pushed.
digest=$(printf '%s\n' "$push_output" | awk -v tag="${image_tag##*:}:" \
    '$1 == tag && $2 == "digest:" { print $3 }')
if [[ ! "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo 'The successful push did not report exactly one valid release digest.' >&2
    exit 1
fi
printf 'image=%s@%s\n' "${image_tag%:*}" "$digest" >> "$GITHUB_OUTPUT"
