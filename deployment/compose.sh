#!/bin/sh
# Resolve all paths independently of the caller's current directory.
set -eu
profile_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bundle_dir=$(CDPATH= cd -- "$profile_dir/.." && pwd)
docker_home=${MIYP_DOCKER_HOME:-$bundle_dir/.docker-home}
docker_config=${MIYP_DOCKER_CONFIG:-$docker_home/.docker}
docker_helper_dir=$profile_dir
umask 077
mkdir -p "$docker_home" "$docker_config"
printf '{"auths":{},"credsStore":"miyp-anonymous"}\n' > "$docker_config/config.json"
export DOCKER_CONFIG="$docker_config"
if env HOME="$docker_home" DOCKER_CONFIG="$docker_config" PATH="$docker_helper_dir:$PATH" \
        docker --config "$docker_config" info >/dev/null 2>&1; then
    exec env HOME="$docker_home" DOCKER_CONFIG="$docker_config" PATH="$docker_helper_dir:$PATH" \
        docker --config "$docker_config" compose \
        --env-file "$profile_dir/deployment.env" \
        -f "$profile_dir/compose.yaml" "$@"
fi
exec sudo env HOME="$docker_home" DOCKER_CONFIG="$docker_config" PATH="$docker_helper_dir:$PATH" \
    docker --config "$docker_config" compose \
    --env-file "$profile_dir/deployment.env" \
    -f "$profile_dir/compose.yaml" "$@"
