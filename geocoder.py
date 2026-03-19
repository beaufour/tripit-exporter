#!/usr/bin/env python3
"""Geocode trip locations and update the database with lat/lng coordinates."""

import time

from geopy.geocoders import Nominatim

from db import extract_visited_locations, get_connection, init_db


def geocode_locations(geolocator, locations):
    """Geocode a list of location strings. Returns dict of location -> (lat, lng)."""
    results = {}
    failed = []

    for loc in sorted(locations):
        print(f"  Geocoding: {loc}...", end="", flush=True)
        try:
            result = geolocator.geocode(loc, timeout=10)
            if result:
                results[loc] = (result.latitude, result.longitude)
                print(f" ({result.latitude:.4f}, {result.longitude:.4f})")
            else:
                print(" NOT FOUND")
                failed.append(loc)
            time.sleep(1.1)  # Nominatim rate limit
        except Exception as e:
            print(f" ERROR: {e}")
            failed.append(loc)

    return results, failed


def main():
    conn = get_connection()
    init_db(conn)

    # Extract visited locations from sub-objects
    print("Extracting visited locations from trips...")
    extract_visited_locations(conn)
    count = conn.execute("SELECT COUNT(*) FROM visited_locations").fetchone()[0]
    print(f"  Found {count} visited locations.")

    # Clean up messy geocode queries before geocoding
    from cleanup_geocodes import clean_query
    rows = conn.execute(
        "SELECT id, geocode_query FROM visited_locations WHERE lat IS NULL OR lng IS NULL"
    ).fetchall()
    cleaned_count = 0
    for row in rows:
        cleaned = clean_query(row["geocode_query"])
        if cleaned is None:
            conn.execute("DELETE FROM visited_locations WHERE id=?", (row["id"],))
            cleaned_count += 1
        elif cleaned != row["geocode_query"]:
            conn.execute(
                "UPDATE visited_locations SET geocode_query=?, lat=NULL, lng=NULL WHERE id=?",
                (cleaned, row["id"]),
            )
            cleaned_count += 1
    if cleaned_count:
        conn.commit()
        print(f"  Cleaned up {cleaned_count} geocode queries.")

    geolocator = Nominatim(user_agent="tripit-map-builder")
    all_failed = []

    # Geocode trip primary locations
    rows = conn.execute("""
        SELECT DISTINCT primary_location
        FROM trips
        WHERE primary_location IS NOT NULL
          AND (lat IS NULL OR lng IS NULL)
    """).fetchall()

    trip_locations = [r["primary_location"] for r in rows]
    if trip_locations:
        print(f"\nGeocoding {len(trip_locations)} trip primary locations...")
        results, failed = geocode_locations(geolocator, trip_locations)
        all_failed.extend(failed)
        for loc, (lat, lng) in results.items():
            conn.execute(
                "UPDATE trips SET lat=?, lng=? WHERE primary_location=?",
                (lat, lng, loc),
            )
        conn.commit()

    # Geocode visited locations
    rows = conn.execute("""
        SELECT DISTINCT geocode_query
        FROM visited_locations
        WHERE lat IS NULL OR lng IS NULL
    """).fetchall()

    visited_queries = [r["geocode_query"] for r in rows]
    if visited_queries:
        print(f"\nGeocoding {len(visited_queries)} visited locations...")
        results, failed = geocode_locations(geolocator, visited_queries)
        all_failed.extend(failed)
        for query, (lat, lng) in results.items():
            conn.execute(
                "UPDATE visited_locations SET lat=?, lng=? WHERE geocode_query=?",
                (lat, lng, query),
            )
        conn.commit()

    if not trip_locations and not visited_queries:
        print("All locations already geocoded.")

    if all_failed:
        print(f"\nFailed ({len(all_failed)}):")
        for loc in all_failed:
            print(f"  - {loc}")

    conn.close()


if __name__ == "__main__":
    main()
