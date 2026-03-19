#!/usr/bin/env python3
"""Import manually curated trips from JSON into the trips database."""

import json
import uuid
from pathlib import Path

from db import get_connection, init_db

MANUAL_TRIPS_FILE = Path("data/manual_trips.json")


def generate_uuid(trip_name):
    """Generate a deterministic UUID from trip name so re-imports are idempotent."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"manual-trip:{trip_name}"))


def import_manual_trips(conn, trips_data):
    """Import manual trips and their places into the database."""
    for trip in trips_data:
        trip_uuid = generate_uuid(trip["name"])

        conn.execute("""
            INSERT INTO trips (uuid, name, start_date, end_date, primary_location, source)
            VALUES (?, ?, ?, ?, ?, 'manual')
            ON CONFLICT(uuid) DO UPDATE SET
                name=excluded.name,
                start_date=excluded.start_date,
                end_date=excluded.end_date,
                primary_location=excluded.primary_location,
                source=excluded.source
        """, (trip_uuid, trip["name"], trip.get("start_date"),
              trip.get("end_date"), trip.get("primary_location")))

        # Clear and re-insert visited locations for this trip
        conn.execute(
            "DELETE FROM visited_locations WHERE trip_uuid=? AND source='manual'",
            (trip_uuid,),
        )

        seen = set()
        for place in trip.get("places", []):
            geocode_query = place["location"]
            # Deduplicate by geocode_query within a trip
            if geocode_query in seen:
                continue
            seen.add(geocode_query)

            conn.execute("""
                INSERT INTO visited_locations
                    (trip_uuid, name, source, geocode_query, lat, lng)
                VALUES (?, ?, 'manual', ?, NULL, NULL)
            """, (trip_uuid, place["name"], geocode_query))

        conn.commit()
        print(f"Imported: {trip['name']} ({len(seen)} unique places)")


def main():
    if not MANUAL_TRIPS_FILE.exists():
        print(f"No {MANUAL_TRIPS_FILE} found")
        return

    with open(MANUAL_TRIPS_FILE) as f:
        trips_data = json.load(f)

    conn = get_connection()
    init_db(conn)

    # Add source column if it doesn't exist yet
    cols = [row[1] for row in conn.execute("PRAGMA table_info(trips)").fetchall()]
    if "source" not in cols:
        conn.execute("ALTER TABLE trips ADD COLUMN source TEXT DEFAULT 'tripit'")
        conn.execute("UPDATE trips SET source='tripit' WHERE source IS NULL")
        conn.commit()

    import_manual_trips(conn, trips_data)

    # Preserve existing geocoded coordinates for visited_locations
    # (extract_visited_locations would overwrite manual entries, so skip it here)
    print("Done. Run geocoder.py to geocode new locations.")
    conn.close()


if __name__ == "__main__":
    main()
