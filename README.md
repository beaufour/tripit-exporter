# tripit-exporter

Export all your TripIt trips to JSON using TripIt's internal API.

Captures flights (with seats, aircraft, travelers), hotels, transport, car rentals, and activities.

## Setup

```bash
uv sync
playwright install chromium
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

## Authentication

The exporter uses Playwright to log in to TripIt and obtain session cookies. The session is saved to `tripit_session.json` and reused on subsequent runs.

### Future: browser cookie extraction

TripIt's login is protected by Akamai bot detection, which requires a real browser to handle. An alternative approach would be to use [`browser_cookie3`](https://github.com/borisbabic/browser_cookie3) to read cookies directly from an already logged-in Chrome or Firefox session. This would eliminate the Playwright dependency entirely -- the user would just need to be logged into TripIt in their browser, and the script would grab the session cookies automatically.
