#!/usr/bin/env python3
"""Geocode trip locations and update the database with lat/lng coordinates."""

import time

from geopy.geocoders import Nominatim

from db import get_connection, init_db


def main():
    conn = get_connection()
    init_db(conn)

    # Find distinct locations that need geocoding
    rows = conn.execute("""
        SELECT DISTINCT primary_location
        FROM trips
        WHERE primary_location IS NOT NULL
          AND (lat IS NULL OR lng IS NULL)
    """).fetchall()

    if not rows:
        print("All locations already geocoded.")
        return

    locations = [r["primary_location"] for r in rows]
    print(f"Found {len(locations)} locations to geocode.")

    geolocator = Nominatim(user_agent="tripit-map-builder")
    geocoded = 0
    failed = []

    for loc in sorted(locations):
        print(f"  Geocoding: {loc}...", end="", flush=True)
        try:
            result = geolocator.geocode(loc, timeout=10)
            if result:
                conn.execute(
                    "UPDATE trips SET lat=?, lng=? WHERE primary_location=?",
                    (result.latitude, result.longitude, loc),
                )
                conn.commit()
                geocoded += 1
                print(f" ({result.latitude:.4f}, {result.longitude:.4f})")
            else:
                print(" NOT FOUND")
                failed.append(loc)
            time.sleep(1.1)  # Nominatim rate limit
        except Exception as e:
            print(f" ERROR: {e}")
            failed.append(loc)

    print(f"\nDone. Geocoded {geocoded} locations.")
    if failed:
        print(f"Failed ({len(failed)}):")
        for loc in failed:
            print(f"  - {loc}")

    conn.close()


if __name__ == "__main__":
    main()
