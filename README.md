# tripit-exporter

Export all your TripIt trips to JSON using TripIt's internal API.

Captures flights (with seats, aircraft, travelers), hotels, transport, car rentals, and activities.

## Setup

```bash
uv sync
uv run playwright install
```

## Configuration

Create a `config.toml` in the project directory:

```toml
email = "you@example.com"
password = "yourpassword"
```

## Usage

```bash
# Export upcoming trips
uv run python exporter.py

# Include past trips
uv run python exporter.py --past

# Limit to N trips (useful for testing)
uv run python exporter.py --limit 5
```

Output is written to `trips.json`.

## Map Visualization

Generate an interactive map of all your trips:

```bash
uv run python build_map.py
open trips_map.html
```

This geocodes each trip's location (cached in `geocache.json` for fast re-runs) and produces a self-contained HTML file with:

- Dark-themed Leaflet map with colored dots per destination
- Year filter buttons to toggle trips by year
- Click any dot to see trip details and flight info
- Live stats for trips, places, and countries

## Authentication

The exporter uses Playwright to log in to TripIt and obtain session cookies. The session is saved to `tripit_session.json` and reused on subsequent runs.

### Future: browser cookie extraction

TripIt's login is protected by Akamai bot detection, which requires a real browser to handle. An alternative approach would be to use [`browser_cookie3`](https://github.com/borisbabic/browser_cookie3) to read cookies directly from an already logged-in Chrome or Firefox session. This would eliminate the Playwright dependency entirely -- the user would just need to be logged into TripIt in their browser, and the script would grab the session cookies automatically.
