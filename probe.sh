#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [start|rebuild]\n' "$0"
    printf '  start    Start and attach to the saved four-probe driver (default).\n'
    printf '  rebuild  Build the image, recreate the driver and start it. Stops the viewer.\n'
}

if (($# > 1)); then
    usage >&2
    exit 2
fi
action="${1:-start}"
case "$action" in
    start|rebuild) ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

for command in sudo docker; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command" >&2
        exit 1
    fi
done

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$action" == rebuild ]]; then
    sudo docker build -t jcs_gamma_probe "$repo_dir"
fi

container_names="$(sudo docker container ls --all --format '{{.Names}}')"
mapfile -t containers <<< "$container_names"

container_exists() {
    local name
    for name in "${containers[@]}"; do
        if [[ "$name" == "$1" ]]; then
            return 0
        fi
    done
    return 1
}

if [[ "$action" == rebuild ]]; then
    printf 'Updating the driver; monitoring and the viewer will stop.\n'
    for name in gamma_probe_plot gamma_probe_ads; do
        if container_exists "$name"; then
            sudo docker stop "$name"
        fi
    done
    if container_exists gamma_probe_ads; then
        sudo docker rm gamma_probe_ads
    fi
    sudo docker create -it --network host --name gamma_probe_ads \
        --mount "type=bind,source=$repo_dir/config,target=/gamma-config,readonly" \
        jcs_gamma_probe roslaunch jcs_gamma_probe gamma_probes_shared_ads.launch \
        probe_config:=/gamma-config/probes.yaml
elif ! container_exists gamma_probe_ads; then
    printf 'Driver container not found. Run: %s rebuild\n' "$0" >&2
    exit 1
fi

printf 'Starting the driver. Once connected, run plot.sh in another terminal.\n'
sudo docker start -ai gamma_probe_ads
