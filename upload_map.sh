#!/usr/bin/env bash
# Upload travel map and data to S3
set -euo pipefail

BUCKET="s3://www.beaufour.dk/travelmap/"
DATA_DIR="$(dirname "$0")/data"

# Upload the HTML map
aws s3 cp "$DATA_DIR/trips_map.html" "${BUCKET}index.html" --content-type "text/html"

# Upload data files
aws s3 cp "$DATA_DIR/trips.json" "${BUCKET}trips.json" --content-type "application/json"
aws s3 cp "$DATA_DIR/trips.csv" "${BUCKET}trips.csv" --content-type "text/csv"

echo "Uploaded to ${BUCKET}"
