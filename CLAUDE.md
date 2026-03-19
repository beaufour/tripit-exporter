# TripIt Exporter

## Package management

Use `uv` as the package manager. Run all Python scripts via `uv run python <script>`.

## Data

All data files live in `data/` (gitignored): `trips.db`, `config.toml`, `tripit_session.json`, `manual_trips.json`, `trips_map.html`, etc.

## Key scripts

- `exporter.py` — Fetches trips from TripIt API into `data/trips.db`
- `import_manual_trips.py` — Imports manually curated trips from `data/manual_trips.json` into the DB
- `geocoder.py` — Geocodes locations in the DB using Nominatim
- `build_map.py` — Generates `data/trips_map.html` interactive map from DB
- `upload_map.sh` — Uploads `data/trips_map.html` to S3 (`s3://www.beaufour.dk/travelmap/index.html`) with public-read ACL

## Trip sources

Trips have a `source` column: `'tripit'` (from API) or `'manual'` (from JSON). Manual trips only have visited places (date + location), no flight/lodging details.
