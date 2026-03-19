#!/usr/bin/env bash
# Upload travel map to S3
set -euo pipefail

BUCKET="s3://www.beaufour.dk/travelmap/"
DATA_DIR="$(dirname "$0")/data"

aws s3 cp "$DATA_DIR/trips_map.html" "${BUCKET}index.html" --content-type "text/html" --acl public-read

echo "Uploaded to ${BUCKET}"
