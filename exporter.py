#!/usr/bin/env python3
"""
TripIt Exporter
Exports all trips from your TripIt account to JSON using TripIt's internal API.

Uses Playwright to log in and obtain session cookies, then calls the API directly.

Requirements:
    pip install playwright
    playwright install chromium

Usage:
    python exporter.py

    Create a config.toml in the current directory:
        email = "you@example.com"
        password = "yourpassword"

On subsequent runs, saved session cookies are reused (no re-login needed).
"""

import argparse
import json
import time
import re
import tomllib
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from db import get_connection, init_db, upsert_trip


CONFIG_FILE = Path("config.toml")
SESSION_FILE = Path("tripit_session.json")

TRIPIT_BASE = "https://www.tripit.com"
API_BASE = f"{TRIPIT_BASE}/api/v2"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)

BROWSER_CONTEXT_OPTIONS = {
    "user_agent": USER_AGENT,
    "viewport": {"width": 1280, "height": 800},
    "locale": "en-US",
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def save_session(context):
    SESSION_FILE.write_text(json.dumps(context.storage_state()))
    print(f"  Session saved to {SESSION_FILE}")


def _launch_context(playwright, **extra):
    browser = playwright.chromium.launch(headless=False, channel="chrome")
    opts = {**BROWSER_CONTEXT_OPTIONS, **extra}
    context = browser.new_context(**opts)
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return browser, context


def login(playwright, email, password):
    print("Logging in...")
    browser, context = _launch_context(playwright)
    page = context.new_page()

    page.goto(f"{TRIPIT_BASE}/account/login")
    time.sleep(3)

    # Dismiss cookie consent banner if present
    for sel in [
        'button[id*="accept"]', 'button[class*="accept"]',
        'button:has-text("Accept")', 'button:has-text("Accept All")',
        'button:has-text("Allow")', '#onetrust-accept-btn-handler',
    ]:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                print("  Dismissed cookie consent banner.")
                time.sleep(1)
                break
        except Exception:
            continue

    # Type like a human to avoid Akamai bot detection
    email_input = page.locator('input[name="loginEmail"], input[type="email"]')
    email_input.click()
    time.sleep(0.5)
    email_input.type(email, delay=80)
    time.sleep(0.3)

    password_input = page.locator('input[name="loginPassword"], input[type="password"]')
    password_input.click()
    time.sleep(0.5)
    password_input.type(password, delay=80)
    time.sleep(1)

    submit_btn = page.locator('button[type="submit"], input[type="submit"]')
    submit_btn.hover()
    time.sleep(0.3)
    submit_btn.click()

    try:
        page.wait_for_url(re.compile(r"tripit\.com/(app/)?(trips|web)"), timeout=30000)
        print("  Login successful.")
    except PlaywrightTimeout:
        page.screenshot(path="login_debug.png")
        print(f"  Debug screenshot saved to login_debug.png")
        print(f"  Current URL: {page.url}")
        raise RuntimeError("Login failed or timed out. Check your credentials.")

    save_session(context)
    return browser, context


def ensure_authenticated(playwright, email, password):
    """Use saved session if available, otherwise log in fresh."""
    if SESSION_FILE.exists():
        print("Found saved session, attempting reuse...")
        storage = json.loads(SESSION_FILE.read_text())
        browser, context = _launch_context(playwright, storage_state=storage)
        page = context.new_page()
        page.goto(f"{TRIPIT_BASE}/app/trips")
        time.sleep(2)
        if "login" not in page.url:
            print("  Session still valid.")
            page.close()
            return browser, context
        print("  Session expired, logging in again...")
        context.close()
        browser.close()

    return login(playwright, email, password)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def api_get(page, path, params=None):
    """Make a GET request to the TripIt API via the browser context."""
    url = f"{API_BASE}/{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    resp = page.evaluate(
        """async (url) => {
            const r = await fetch(url, {
                credentials: 'include',
                headers: {
                    'accept': 'application/json',
                    'x-requested-with': 'XMLHttpRequest',
                    'x-tripit-app-info': 'web/0.0.2',
                },
            });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        }""",
        url,
    )
    return resp


def list_trips(page, past=False, traveler=True):
    """Fetch all trips (handles pagination).

    Args:
        past: If True, fetch past trips instead of upcoming.
        traveler: If True, fetch your trips. If False, fetch others' trips.
    """
    all_trips = []
    page_num = 1

    while True:
        params = {
            "exclude_types": "weather",
            "page_size": "50",
            "past": str(past).lower(),
            "should_sort_trips_by_date": "true",
            "traveler": str(traveler).lower(),
            "trip_permission_filter": "all",
            "page_num": str(page_num),
        }
        data = api_get(page, "list/trip", params)

        trips = data.get("Trip", [])
        # API returns a single object instead of a list when there's only one trip
        if isinstance(trips, dict):
            trips = [trips]
        all_trips.extend(trips)

        max_page = int(data.get("max_page", 1))
        if page_num >= max_page:
            break
        page_num += 1

    return all_trips


def get_trip_detail(page, trip_uuid):
    """Fetch full trip details including all objects."""
    return api_get(
        page,
        f"get/trip/uuid/{trip_uuid}/include_objects/true",
        {"exclude_types": "weather"},
    )


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def _ensure_list(val):
    """API returns a single object instead of a list when there's only one item."""
    if val is None:
        return []
    if isinstance(val, dict):
        return [val]
    return val


def extract_trip(detail):
    """Extract a clean trip dict from the API response."""
    trip_data = detail["Trip"]
    trip = {
        "uuid": trip_data["uuid"],
        "name": trip_data["display_name"],
        "start_date": trip_data["start_date"],
        "end_date": trip_data["end_date"],
        "primary_location": trip_data.get("primary_location"),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "flights": [],
        "lodging": [],
        "transport": [],
        "car_rentals": [],
        "activities": [],
    }

    # Flights
    for air in _ensure_list(detail.get("AirObject")):
        segments = _ensure_list(air.get("Segment"))
        for seg in segments:
            flight = {
                "origin": seg.get("start_airport_code"),
                "origin_name": seg.get("start_airport_name"),
                "destination": seg.get("end_airport_code"),
                "destination_name": seg.get("end_airport_name"),
                "departure": _format_datetime(seg.get("StartDateTime")),
                "arrival": _format_datetime(seg.get("EndDateTime")),
                "airline": seg.get("marketing_airline"),
                "flight_number": f"{seg.get('marketing_airline_code', '')} {seg.get('marketing_flight_number', '')}".strip(),
                "operating_airline": seg.get("operating_airline"),
                "operating_flight_number": (
                    f"{seg.get('operating_airline_code', '')} {seg.get('operating_flight_number', '')}".strip()
                    if seg.get("operating_airline_code") else None
                ),
                "confirmation": air.get("supplier_conf_num"),
                "booking_site_conf": air.get("booking_site_conf_num"),
                "seats": seg.get("seats"),
                "service_class": seg.get("service_class"),
                "aircraft": seg.get("aircraft_display_name"),
                "duration": seg.get("duration"),
                "stops": seg.get("stops"),
                "terminal_departure": seg.get("start_terminal"),
                "terminal_arrival": seg.get("end_terminal"),
                "meal": seg.get("meal"),
            }
            # Traveler info
            travelers = _ensure_list(air.get("Traveler"))
            if travelers:
                flight["travelers"] = [
                    {
                        "name": f"{t.get('first_name', '')} {t.get('last_name', '')}".strip(),
                        "ticket_num": t.get("ticket_num"),
                        "frequent_flyer": t.get("frequent_traveler_num"),
                    }
                    for t in travelers
                ]
            trip["flights"].append(flight)

    # Lodging
    for lodge in _ensure_list(detail.get("LodgingObject")):
        hotel = {
            "name": lodge.get("display_name"),
            "confirmation": lodge.get("supplier_conf_num"),
            "check_in": _format_datetime(lodge.get("StartDateTime")),
            "check_out": _format_datetime(lodge.get("EndDateTime")),
            "address": _format_address(lodge.get("Address")),
            "phone": lodge.get("supplier_phone"),
            "booking_site": lodge.get("booking_site_name"),
            "booking_site_conf": lodge.get("booking_site_conf_num"),
        }
        trip["lodging"].append(hotel)

    # Transport
    for transport in _ensure_list(detail.get("TransportObject")):
        segments = _ensure_list(transport.get("Segment"))
        for seg in segments:
            item = {
                "name": transport.get("display_name"),
                "confirmation": transport.get("supplier_conf_num"),
                "departure": _format_datetime(seg.get("StartDateTime")),
                "arrival": _format_datetime(seg.get("EndDateTime")),
                "start_location": seg.get("start_location_name"),
                "end_location": seg.get("end_location_name"),
                "start_address": _format_address(seg.get("StartLocationAddress")),
                "end_address": _format_address(seg.get("EndLocationAddress")),
            }
            trip["transport"].append(item)

    # Car rentals
    for car in _ensure_list(detail.get("CarObject")):
        rental = {
            "company": car.get("display_name"),
            "confirmation": car.get("supplier_conf_num"),
            "pick_up": _format_datetime(car.get("StartDateTime")),
            "drop_off": _format_datetime(car.get("EndDateTime")),
            "pick_up_location": _format_address(car.get("start_address") or car.get("Address")),
            "drop_off_location": _format_address(car.get("end_address")),
        }
        trip["car_rentals"].append(rental)

    # Activities
    for act in _ensure_list(detail.get("ActivityObject")):
        activity = {
            "name": act.get("display_name"),
            "location": act.get("location_name"),
            "start": _format_datetime(act.get("StartDateTime")),
            "end": _format_datetime(act.get("EndDateTime")),
            "address": _format_address(act.get("Address")),
            "phone": act.get("supplier_phone"),
            "url": act.get("supplier_url"),
        }
        trip["activities"].append(activity)

    # Remove empty categories
    for key in ["flights", "lodging", "transport", "car_rentals", "activities"]:
        if not trip[key]:
            del trip[key]

    return trip


def _format_datetime(dt):
    if not dt:
        return None
    date = dt.get("date", "")
    time_str = dt.get("time", "")
    tz = dt.get("timezone", "")
    if date and time_str:
        return f"{date} {time_str} ({tz})"
    return date or None


def _format_address(addr):
    if not addr:
        return None
    if isinstance(addr, str):
        return addr
    return addr.get("address")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_config():
    """Load config from config.toml if it exists."""
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as f:
            return tomllib.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(description="Export TripIt trips to SQLite")
    parser.add_argument("--email", help="TripIt login email")
    parser.add_argument("--password", help="TripIt login password")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of trips to export (0 = all)",
    )
    parser.add_argument(
        "--past", action="store_true",
        help="Include past trips",
    )
    parser.add_argument(
        "--others", action="store_true",
        help="Include trips where you are not the traveler",
    )
    args = parser.parse_args()

    config = load_config()
    email = args.email or config.get("email")
    password = args.password or config.get("password")
    if not email or not password:
        parser.error("email and password are required (via --email/--password flags or config.toml)")

    conn = get_connection()
    init_db(conn)

    with sync_playwright() as playwright:
        browser, context = ensure_authenticated(playwright, email, password)
        page = context.new_page()

        # Navigate to TripIt so API calls use the right cookies/origin
        page.goto(f"{TRIPIT_BASE}/app/trips")
        time.sleep(2)

        # List all trips
        print("\nFetching trip list...")
        trip_summaries = list_trips(page, past=False)
        if args.past:
            trip_summaries += list_trips(page, past=True)
        if args.others:
            trip_summaries += list_trips(page, past=False, traveler=False)
            if args.past:
                trip_summaries += list_trips(page, past=True, traveler=False)
        print(f"  Found {len(trip_summaries)} trips.")

        if args.limit:
            trip_summaries = trip_summaries[:args.limit]
            print(f"  (Limited to {args.limit})")

        # Fetch full details for each trip
        exported = 0
        errors = []
        for i, summary in enumerate(trip_summaries, 1):
            name = summary["display_name"]
            uuid = summary["uuid"]
            print(f"  [{i}/{len(trip_summaries)}] {name}...", end="", flush=True)
            try:
                detail = get_trip_detail(page, uuid)
                trip = extract_trip(detail)
                upsert_trip(conn, trip)
                exported += 1
                print(" ok")
            except Exception as e:
                print(f" ERROR: {e}")
                errors.append({"uuid": uuid, "name": name, "error": str(e)})

        browser.close()

    conn.commit()
    conn.close()

    print(f"\nDone. {exported} trips saved to {get_connection().execute('SELECT count(*) FROM trips').fetchone()[0]} total in DB, {len(errors)} errors.")
    if errors:
        for e in errors:
            print(f"  ✗ {e['name']}: {e['error']}")


if __name__ == "__main__":
    main()
