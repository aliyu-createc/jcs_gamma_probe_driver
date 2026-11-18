#!/usr/bin/env bash
set -euo pipefail

for command in sudo docker curl xdg-open; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command" >&2
        exit 1
    fi
done

url="http://127.0.0.1:8080"
sudo docker start gamma_probe_plot

for ((attempt = 0; attempt < 30; attempt++)); do
    if curl --fail --silent --max-time 1 --output /dev/null "$url/api/data"; then
        printf 'Opening %s\n' "$url"
        xdg-open "$url"
        exit 0
    fi
    sleep 1
done

printf 'Plot did not become ready. Start the driver first and check: sudo docker logs gamma_probe_plot\n' >&2
exit 1
