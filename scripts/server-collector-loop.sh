#!/bin/sh
# Keep the VPS collector attached to its sibling API service.  The collector
# normally targets Railway when FINANCIALS_PUSH_URL is absent, so this loop is
# intentionally only used by docker-compose.yml, which sets an internal URL.
set -eu

interval="${COLLECTOR_INTERVAL_SECONDS:-86400}"
if [ -z "${ADMIN_API_SECRET:-}" ]; then
    echo "ADMIN_API_SECRET is required for the local collector to write data." >&2
    exit 78
fi
if [ "${FINANCIALS_PUSH_URL:-}" != "http://uzstock-web:8000" ]; then
    echo "FINANCIALS_PUSH_URL must be http://uzstock-web:8000 in the VPS collector." >&2
    exit 64
fi
case "$interval" in
    ''|*[!0-9]*)
        echo "COLLECTOR_INTERVAL_SECONDS must be a positive integer" >&2
        exit 64
        ;;
esac
if [ "$interval" -lt 1 ]; then
    echo "COLLECTOR_INTERVAL_SECONDS must be a positive integer" >&2
    exit 64
fi

until python -c "import requests; requests.get('http://uzstock-web:8000/api/catalog/status', timeout=5).raise_for_status()"; do
    echo "Waiting for the local API before collecting data..." >&2
    sleep 5
done

while :; do
    if ! python collector_financials.py; then
        echo "Collector run failed; it will retry after ${interval} seconds." >&2
    fi
    sleep "$interval"
done
