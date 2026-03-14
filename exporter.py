#!/usr/bin/env python3
"""
TripIt Scraper
Scrapes all trips from your TripIt account and exports to JSON + CSV.

Requirements:
    pip install playwright pandas
    playwright install chromium

Usage:
    python tripit_scraper.py --email you@example.com --password yourpassword

    Or create a config.toml in the current directory:
        email = "you@example.com"
        password = "yourpassword"

On subsequent runs, saved session cookies are reused (no re-login needed).
"""

import argparse
import json
import csv
import time
import re
import tomllib
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


CONFIG_FILE = Path("config.toml")
SESSION_FILE = Path("tripit_session.json")
OUTPUT_JSON = Path("trips.json")
OUTPUT_CSV = Path("trips.csv")

TRIPIT_BASE = "https://www.tripit.com"
TRIPS_URL = f"{TRIPIT_BASE}/trips"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def save_session(context):
    SESSION_FILE.write_text(json.dumps(context.storage_state()))
    print(f"  Session saved to {SESSION_FILE}")


def load_session(playwright):
    """Return a browser context with saved cookies, or None if no session."""
    if not SESSION_FILE.exists():
        return None
    storage = json.loads(SESSION_FILE.read_text())
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(storage_state=storage)
    return browser, context


def login(playwright, email, password):
    print("Logging in...")
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto(f"{TRIPIT_BASE}/account/login")
    page.fill('input[name="loginEmail"], input[type="email"]', email)
    page.fill('input[name="loginPassword"], input[type="password"]', password)
    page.click('button[type="submit"], input[type="submit"]')

    try:
        page.wait_for_url(re.compile(r"tripit\.com/trips|tripit\.com/web"), timeout=15000)
        print("  Login successful.")
    except PlaywrightTimeout:
        raise RuntimeError("Login failed or timed out. Check your credentials.")

    save_session(context)
    return browser, context


def ensure_authenticated(playwright, email, password):
    """Use saved session if available, otherwise log in fresh."""
    if SESSION_FILE.exists():
        print("Found saved session, attempting reuse...")
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=json.loads(SESSION_FILE.read_text()))
        page = context.new_page()
        page.goto(TRIPS_URL)
        time.sleep(2)
        if "login" in page.url:
            print("  Session expired, logging in again...")
            context.close()
            browser.close()
            return login(playwright, email, password)
        print("  Session still valid.")
        return browser, context

    return login(playwright, email, password)


# ---------------------------------------------------------------------------
# Trip list scraping
# ---------------------------------------------------------------------------

def get_all_trip_urls(page):
    """Navigate the trips list and collect all trip detail URLs."""
    print("\nCollecting trip URLs...")
    trip_urls = []
    page.goto(TRIPS_URL)
    time.sleep(3)

    while True:
        # Collect trip links on current page
        # TripIt uses various selectors depending on version; try a few
        links = page.query_selector_all('a[href*="/trip/show/"], a[href*="/trips/"]')
        for link in links:
            href = link.get_attribute("href")
            if href and "/trip/show/" in href:
                full_url = href if href.startswith("http") else f"{TRIPIT_BASE}{href}"
                if full_url not in trip_urls:
                    trip_urls.append(full_url)

        # Try to find a "next page" / "load more" button
        next_btn = page.query_selector('a[aria-label="Next"], a.next, button.load-more, [data-testid="next-page"]')
        if next_btn:
            next_btn.click()
            time.sleep(2)
        else:
            break

    # Also try the "past trips" section if present
    past_link = page.query_selector('a[href*="past"], a[href*="archive"]')
    if past_link:
        past_link.click()
        time.sleep(2)
        past_links = page.query_selector_all('a[href*="/trip/show/"]')
        for link in past_links:
            href = link.get_attribute("href")
            if href:
                full_url = href if href.startswith("http") else f"{TRIPIT_BASE}{href}"
                if full_url not in trip_urls:
                    trip_urls.append(full_url)

    print(f"  Found {len(trip_urls)} trip URLs.")
    return trip_urls


# ---------------------------------------------------------------------------
# Trip detail scraping
# ---------------------------------------------------------------------------

def safe_text(el):
    return el.inner_text().strip() if el else None


def scrape_trip(page, url):
    """Scrape a single trip detail page and return a dict."""
    page.goto(url)
    time.sleep(1.5)

    trip = {
        "url": url,
        "scraped_at": datetime.utcnow().isoformat(),
        "name": None,
        "dates": None,
        "destination": None,
        "segments": [],
        "notes": [],
        "raw_text": None,
    }

    # Trip name
    for sel in ["h1", ".trip-name", '[data-testid="trip-name"]', ".TripHeader__name"]:
        el = page.query_selector(sel)
        if el:
            trip["name"] = safe_text(el)
            break

    # Dates / destination — often in a subtitle or header meta
    for sel in [".trip-dates", ".TripHeader__dates", ".trip-header-dates"]:
        el = page.query_selector(sel)
        if el:
            trip["dates"] = safe_text(el)
            break

    for sel in [".trip-destination", ".TripHeader__destination", ".trip-header-location"]:
        el = page.query_selector(sel)
        if el:
            trip["destination"] = safe_text(el)
            break

    # Segments — flights, hotels, cars, activities etc.
    # TripIt renders these as cards/sections
    segment_containers = page.query_selector_all(
        ".plan-item, .segment, [data-testid='plan-item'], "
        ".PlanItem, .itinerary-item, .trip-item"
    )
    for container in segment_containers:
        seg = {}
        seg["type"] = None
        seg["text"] = safe_text(container)

        # Try to get segment type from icon class or label
        type_el = container.query_selector(".plan-type, .segment-type, .icon-label, [class*='type']")
        if type_el:
            seg["type"] = safe_text(type_el)

        # Confirmation number
        confirm_match = re.search(
            r"(?:confirmation|conf(?:irmation)?\.?\s*#?|record locator)[:\s]+([A-Z0-9]{4,10})",
            seg.get("text", ""),
            re.IGNORECASE,
        )
        seg["confirmation"] = confirm_match.group(1) if confirm_match else None

        if seg["text"]:
            trip["segments"].append(seg)

    # Notes
    note_els = page.query_selector_all(".note, .trip-note, [data-testid='note']")
    for note_el in note_els:
        text = safe_text(note_el)
        if text:
            trip["notes"].append(text)

    # Fallback: capture all visible text for the trip page
    # Useful for anything the structured selectors miss
    body_el = page.query_selector("main, #content, .trip-detail, body")
    if body_el:
        trip["raw_text"] = body_el.inner_text()[:5000]  # cap at 5k chars

    return trip


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_json(trips):
    OUTPUT_JSON.write_text(json.dumps(trips, indent=2, ensure_ascii=False))
    print(f"  JSON saved → {OUTPUT_JSON} ({len(trips)} trips)")


def save_csv(trips):
    rows = []
    for trip in trips:
        base = {
            "name": trip.get("name"),
            "dates": trip.get("dates"),
            "destination": trip.get("destination"),
            "url": trip.get("url"),
            "segment_count": len(trip.get("segments", [])),
            "notes": " | ".join(trip.get("notes", [])),
            "scraped_at": trip.get("scraped_at"),
        }
        # Flatten segments into one row per segment for easy filtering
        segs = trip.get("segments", [])
        if segs:
            for seg in segs:
                row = dict(base)
                row["segment_type"] = seg.get("type")
                row["segment_text"] = (seg.get("text") or "")[:300]
                row["confirmation"] = seg.get("confirmation")
                rows.append(row)
        else:
            rows.append(base)

    if not rows:
        print("  No rows to write to CSV.")
        return

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"  CSV saved  → {OUTPUT_CSV} ({len(rows)} rows)")


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
    parser = argparse.ArgumentParser(description="Scrape TripIt trips to JSON + CSV")
    parser.add_argument("--email", help="TripIt login email")
    parser.add_argument("--password", help="TripIt login password")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of trips to scrape (0 = all, useful for testing)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip trips already in trips.json (resume interrupted run)"
    )
    args = parser.parse_args()

    config = load_config()
    email = args.email or config.get("email")
    password = args.password or config.get("password")
    if not email or not password:
        parser.error("email and password are required (via --email/--password flags or config.toml)")

    # Load existing trips if resuming
    existing = {}
    if args.resume and OUTPUT_JSON.exists():
        existing_trips = json.loads(OUTPUT_JSON.read_text())
        existing = {t["url"]: t for t in existing_trips}
        print(f"Resuming: {len(existing)} trips already scraped.")

    with sync_playwright() as playwright:
        browser, context = ensure_authenticated(playwright, email, password)
        page = context.new_page()

        trip_urls = get_all_trip_urls(page)

        if args.limit:
            trip_urls = trip_urls[:args.limit]
            print(f"  (Limited to first {args.limit} trips)")

        # Filter already-scraped if resuming
        to_scrape = [u for u in trip_urls if u not in existing]
        print(f"\nScraping {len(to_scrape)} trips (skipping {len(trip_urls) - len(to_scrape)} already done)...")

        trips = list(existing.values())
        errors = []

        for i, url in enumerate(to_scrape, 1):
            print(f"  [{i}/{len(to_scrape)}] {url}", end="", flush=True)
            try:
                trip = scrape_trip(page, url)
                trips.append(trip)
                label = trip.get("name") or "(unnamed)"
                print(f" → {label}")
            except Exception as e:
                print(f" ✗ ERROR: {e}")
                errors.append({"url": url, "error": str(e)})

            # Save incrementally every 10 trips so progress isn't lost
            if i % 10 == 0:
                save_json(trips)

        browser.close()

    print(f"\nDone. {len(trips)} trips scraped, {len(errors)} errors.")
    if errors:
        err_file = Path("tripit_errors.json")
        err_file.write_text(json.dumps(errors, indent=2))
        print(f"  Errors logged → {err_file}")

    print("\nSaving output...")
    save_json(trips)
    save_csv(trips)


if __name__ == "__main__":
    main()