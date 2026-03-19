"""SQLite database schema and helpers for trip data."""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILE = Path("data/trips.db")


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trips (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            primary_location TEXT,
            lat REAL,
            lng REAL,
            exported_at TEXT
        );

        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_uuid TEXT NOT NULL REFERENCES trips(uuid) ON DELETE CASCADE,
            origin TEXT,
            origin_name TEXT,
            destination TEXT,
            destination_name TEXT,
            departure TEXT,
            arrival TEXT,
            airline TEXT,
            flight_number TEXT,
            operating_airline TEXT,
            operating_flight_number TEXT,
            confirmation TEXT,
            booking_site_conf TEXT,
            seats TEXT,
            service_class TEXT,
            aircraft TEXT,
            duration TEXT,
            stops TEXT,
            terminal_departure TEXT,
            terminal_arrival TEXT,
            meal TEXT
        );

        CREATE TABLE IF NOT EXISTS travelers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_id INTEGER NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
            name TEXT,
            ticket_num TEXT,
            frequent_flyer TEXT
        );

        CREATE TABLE IF NOT EXISTS lodging (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_uuid TEXT NOT NULL REFERENCES trips(uuid) ON DELETE CASCADE,
            name TEXT,
            confirmation TEXT,
            check_in TEXT,
            check_out TEXT,
            address TEXT,
            phone TEXT,
            booking_site TEXT,
            booking_site_conf TEXT
        );

        CREATE TABLE IF NOT EXISTS transport (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_uuid TEXT NOT NULL REFERENCES trips(uuid) ON DELETE CASCADE,
            name TEXT,
            confirmation TEXT,
            departure TEXT,
            arrival TEXT,
            start_location TEXT,
            end_location TEXT,
            start_address TEXT,
            end_address TEXT
        );

        CREATE TABLE IF NOT EXISTS car_rentals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_uuid TEXT NOT NULL REFERENCES trips(uuid) ON DELETE CASCADE,
            company TEXT,
            confirmation TEXT,
            pick_up TEXT,
            drop_off TEXT,
            pick_up_location TEXT,
            drop_off_location TEXT
        );

        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_uuid TEXT NOT NULL REFERENCES trips(uuid) ON DELETE CASCADE,
            name TEXT,
            location TEXT,
            start TEXT,
            "end" TEXT,
            address TEXT,
            phone TEXT,
            url TEXT
        );

        CREATE TABLE IF NOT EXISTS visited_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_uuid TEXT NOT NULL REFERENCES trips(uuid) ON DELETE CASCADE,
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            geocode_query TEXT NOT NULL,
            lat REAL,
            lng REAL
        );
    """)


def upsert_trip(conn, trip):
    """Insert or update a trip and all its related records."""
    uuid = trip["uuid"]

    # Upsert trip row (preserve existing lat/lng if not provided)
    conn.execute("""
        INSERT INTO trips (uuid, name, start_date, end_date, primary_location, exported_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(uuid) DO UPDATE SET
            name=excluded.name,
            start_date=excluded.start_date,
            end_date=excluded.end_date,
            primary_location=excluded.primary_location,
            exported_at=excluded.exported_at
    """, (uuid, trip["name"], trip.get("start_date"), trip.get("end_date"),
          trip.get("primary_location"), trip.get("exported_at")))

    # Clear child records and re-insert
    conn.execute("DELETE FROM flights WHERE trip_uuid=?", (uuid,))
    conn.execute("DELETE FROM lodging WHERE trip_uuid=?", (uuid,))
    conn.execute("DELETE FROM transport WHERE trip_uuid=?", (uuid,))
    conn.execute("DELETE FROM car_rentals WHERE trip_uuid=?", (uuid,))
    conn.execute("DELETE FROM activities WHERE trip_uuid=?", (uuid,))

    for flight in trip.get("flights", []):
        cur = conn.execute("""
            INSERT INTO flights (trip_uuid, origin, origin_name, destination,
                destination_name, departure, arrival, airline, flight_number,
                operating_airline, operating_flight_number, confirmation,
                booking_site_conf, seats, service_class, aircraft, duration,
                stops, terminal_departure, terminal_arrival, meal)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (uuid, flight.get("origin"), flight.get("origin_name"),
              flight.get("destination"), flight.get("destination_name"),
              flight.get("departure"), flight.get("arrival"),
              flight.get("airline"), flight.get("flight_number"),
              flight.get("operating_airline"), flight.get("operating_flight_number"),
              flight.get("confirmation"), flight.get("booking_site_conf"),
              flight.get("seats"), flight.get("service_class"),
              flight.get("aircraft"), flight.get("duration"),
              flight.get("stops"), flight.get("terminal_departure"),
              flight.get("terminal_arrival"), flight.get("meal")))
        flight_id = cur.lastrowid
        for traveler in flight.get("travelers", []):
            conn.execute("""
                INSERT INTO travelers (flight_id, name, ticket_num, frequent_flyer)
                VALUES (?,?,?,?)
            """, (flight_id, traveler.get("name"), traveler.get("ticket_num"),
                  traveler.get("frequent_flyer")))

    for lodge in trip.get("lodging", []):
        conn.execute("""
            INSERT INTO lodging (trip_uuid, name, confirmation, check_in,
                check_out, address, phone, booking_site, booking_site_conf)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (uuid, lodge.get("name"), lodge.get("confirmation"),
              lodge.get("check_in"), lodge.get("check_out"),
              lodge.get("address"), lodge.get("phone"),
              lodge.get("booking_site"), lodge.get("booking_site_conf")))

    for t in trip.get("transport", []):
        conn.execute("""
            INSERT INTO transport (trip_uuid, name, confirmation, departure,
                arrival, start_location, end_location, start_address, end_address)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (uuid, t.get("name"), t.get("confirmation"),
              t.get("departure"), t.get("arrival"),
              t.get("start_location"), t.get("end_location"),
              t.get("start_address"), t.get("end_address")))

    for car in trip.get("car_rentals", []):
        conn.execute("""
            INSERT INTO car_rentals (trip_uuid, company, confirmation,
                pick_up, drop_off, pick_up_location, drop_off_location)
            VALUES (?,?,?,?,?,?,?)
        """, (uuid, car.get("company"), car.get("confirmation"),
              car.get("pick_up"), car.get("drop_off"),
              car.get("pick_up_location"), car.get("drop_off_location")))

    for act in trip.get("activities", []):
        conn.execute("""
            INSERT INTO activities (trip_uuid, name, location, start, "end",
                address, phone, url)
            VALUES (?,?,?,?,?,?,?,?)
        """, (uuid, act.get("name"), act.get("location"),
              act.get("start"), act.get("end"),
              act.get("address"), act.get("phone"), act.get("url")))


def extract_visited_locations(conn):
    """Extract visited locations from flights, lodging, activities, etc."""
    # Cache existing geocoded coordinates so we don't lose them on re-extraction
    existing = {}
    for row in conn.execute(
        "SELECT geocode_query, lat, lng FROM visited_locations WHERE lat IS NOT NULL"
    ).fetchall():
        existing[row["geocode_query"]] = (row["lat"], row["lng"])

    # Only delete non-manual locations; manual ones are managed by import_manual_trips
    conn.execute("DELETE FROM visited_locations WHERE source != 'manual'")

    trip_uuids = [r["uuid"] for r in conn.execute("SELECT uuid FROM trips").fetchall()]

    for uuid in trip_uuids:
        locations = []

        # Flights: get non-connection airports
        flights = conn.execute("""
            SELECT origin, origin_name, destination, destination_name, departure
            FROM flights WHERE trip_uuid = ?
            ORDER BY departure
        """, (uuid,)).fetchall()

        # Identify connection airports: if flight[i].destination == flight[i+1].origin
        # and they depart within 1 day, that airport is just a layover
        connections = set()
        for i in range(len(flights) - 1):
            if (flights[i]["destination"]
                    and flights[i]["destination"] == flights[i + 1]["origin"]):
                # Check time gap — only a connection if departures are <=1 day apart
                dep_a = flights[i]["departure"]
                dep_b = flights[i + 1]["departure"]
                if dep_a and dep_b:
                    try:
                        # Parse "2012-07-18 12:25:00 (Europe/Copenhagen)" → date part
                        da = datetime.strptime(dep_a[:10], "%Y-%m-%d")
                        db = datetime.strptime(dep_b[:10], "%Y-%m-%d")
                        if (db - da).days <= 1:
                            connections.add(flights[i]["destination"])
                    except ValueError:
                        # Can't parse dates, assume connection to be safe
                        connections.add(flights[i]["destination"])

        seen_airports = set()
        for f in flights:
            for code, name in [
                (f["origin"], f["origin_name"]),
                (f["destination"], f["destination_name"]),
            ]:
                if code and code not in connections and code not in seen_airports:
                    seen_airports.add(code)
                    display = name or code
                    locations.append((display, "flight", display))

        # Lodging
        for lodge in conn.execute(
            "SELECT name, address FROM lodging WHERE trip_uuid=?", (uuid,)
        ).fetchall():
            query = lodge["address"] or lodge["name"]
            if query and query.lower() not in ("lodging", "hotel"):
                locations.append((lodge["name"] or query, "lodging", query))

        # Activities
        for act in conn.execute(
            "SELECT name, location, address FROM activities WHERE trip_uuid=?", (uuid,)
        ).fetchall():
            query = act["address"] or act["location"]
            if query:
                locations.append((act["name"] or query, "activity", query))

        # Car rentals
        for car in conn.execute(
            "SELECT company, pick_up_location, drop_off_location FROM car_rentals WHERE trip_uuid=?",
            (uuid,),
        ).fetchall():
            if car["pick_up_location"]:
                locations.append((
                    car["company"] or car["pick_up_location"],
                    "car_rental",
                    car["pick_up_location"],
                ))
            if (car["drop_off_location"]
                    and car["drop_off_location"] != car["pick_up_location"]):
                locations.append((
                    car["company"] or car["drop_off_location"],
                    "car_rental",
                    car["drop_off_location"],
                ))

        # Transport
        for t in conn.execute(
            "SELECT name, start_location, start_address, end_location, end_address FROM transport WHERE trip_uuid=?",
            (uuid,),
        ).fetchall():
            start_query = t["start_address"] or t["start_location"]
            if start_query:
                locations.append((t["name"] or start_query, "transport", start_query))
            end_query = t["end_address"] or t["end_location"]
            if end_query and end_query != start_query:
                locations.append((t["name"] or end_query, "transport", end_query))

        for name, source, query in locations:
            cached = existing.get(query)
            lat, lng = cached if cached else (None, None)
            conn.execute("""
                INSERT INTO visited_locations (trip_uuid, name, source, geocode_query, lat, lng)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (uuid, name, source, query, lat, lng))

    conn.commit()
