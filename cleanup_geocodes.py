#!/usr/bin/env python3
"""Clean up messy TripIt geocode queries so Nominatim can resolve them.

Applies a series of transformations to visited_locations.geocode_query values
that failed geocoding (lat/lng is NULL). Changes are written back to the DB
so the next geocoder.py run can pick them up.

Run:  uv run python cleanup_geocodes.py [--dry-run]
Then: uv run python geocoder.py
"""

import re
import sys

from db import get_connection

# Country code → full name (ISO 3166-1 alpha-2 codes seen in the data)
COUNTRY_CODES = {
    "DE": "Germany",
    "DK": "Denmark",
    "ES": "Spain",
    "FR": "France",
    "ID": "Indonesia",
    "IT": "Italy",
    "NO": "Norway",
    "SE": "Sweden",
    "TC": "Turks and Caicos Islands",
    "UK": "United Kingdom",
    "US": "United States",
}

# Exact replacements: bad query → clean query
# Use for entries that can't be fixed by rules alone
MANUAL_OVERRIDES = {
    "33 8 92700210": None,  # phone number, not an address
    "kids birthday party": None,  # not a location
    "HEATHROW, TERM 3": "Heathrow Airport, London, United Kingdom",
    "Athens Eleftherios Venizelos International Airport": "Athens Airport, Greece",
    "Munich Franz Joseph Strauss Airport": "Munich Airport, Germany",
    "Paris Charles de Gaulle Airport": "Charles de Gaulle Airport, Paris, France",
    "Newark Liberty International Airport (EWR), Brewster Road, Newark, NJ, USA":
        "Newark Liberty International Airport, Newark, NJ, USA",
    "Tamarind by Elegant Hotels": "Tamarind Hotel, Barbados",
    "the Post Hotel & Spa in Lake Louise": "Post Hotel, Lake Louise, Alberta, Canada",
    "Mile post 231.1, George Parks Highway": "Denali National Park, Alaska, USA",
    "Rabot Estate, Soufrière, St. Lucia, West Indies": "Soufrière, Saint Lucia",
    "Grace Bay Po Box 128. PROVIDENCIALES TC TKCA 1ZZ":
        "Grace Bay, Providenciales, Turks and Caicos Islands",
    "Grace Bay Circle, Dr, Grace Bay TKCA 1ZZ, Turks and Caicos Islands":
        "Grace Bay, Providenciales, Turks and Caicos Islands",
    "Grace Bay Club, Dr, Grace Bay, Turks and Caicos Islands":
        "Grace Bay, Providenciales, Turks and Caicos Islands",
    "Balmoral Forest, Canterbury, New Zealand":
        "Balmoral, Canterbury, New Zealand",
    "Ban Tai, Koh Phangan, Thailand": "Koh Phangan, Thailand",
    "190 45 Stockholm-Arlanda, Sweden": "Stockholm Arlanda Airport, Sweden",
    "Greenleaf Trail, Route 93, NH": "Greenleaf Trail, Franconia, NH, USA",
    "10-12 Bld du Maréchal Foch 21200 BEAUNE (FRANCE)":
        "Boulevard Maréchal Foch, Beaune, France",
    "505 N STATE STREET, 60654 USA CHICAGO, IL":
        "505 N State Street, Chicago, IL 60654, USA",
    "Copenhagen Central Post Building, Tietgensgade 35-39, 1704 København, Denmark":
        "Tietgensgade 35, Copenhagen, Denmark",
    "Strawberry Hills , Satobari, Near Dal Lake, McLeod Ganj, Dharamshala Cantt, Satovari, Dharamshala, Himachal Pradesh 176216, India":
        "McLeod Ganj, Dharamshala, Himachal Pradesh, India",
    "Nazrul Islam Avenue VIP Road, Jora Mandir, Baguiati, Kolkata":
        "Baguiati, Kolkata, India",
    "Flat 16, Hampshire House, 12 Hyde Park Place, London, W2 2LH":
        "12 Hyde Park Place, London, W2 2LH, United Kingdom",
    "1114 E. Putnam Ave, Riverside, CT, 06878 United States of America":
        "Riverside, Greenwich, CT, USA",
    "12 Hyde Park Pl, St George's Fields, London W2 2LH, UK":
        "12 Hyde Park Place, London, W2 2LH, United Kingdom",
    "127 West Huron, at LaSalle, Chicago, IL, 60654 United States of America":
        "127 West Huron Street, Chicago, IL, USA",
    "3116 Route 44/55, Gardiner, NY":
        "Gardiner, NY, USA",
    "4 Rue De Jussieu, Lyon, 69002, France":
        "Lyon 2e Arrondissement, France",
    "8 rue Saint Antoine Quebec - G1K 4C9 - (Quebec) Canada":
        "8 Rue Saint-Antoine, Québec, Canada",
    "Av. Rotary Internacional, s/n, Nueva Andalucía, 29660 Marbella, Málaga, Spain":
        "Nueva Andalucía, Marbella, Spain",
    "BRUNKEBERGSTORG 15 STOCKHOLM SE 11151, STOCKHOLM, 11151, SE":
        "Brunkebergstorg 15, Stockholm, Sweden",
    "Biskop Gunnerusgate 3, Oslo, 0155, NO":
        "Biskop Gunnerus' gate 3, Oslo, Norway",
    "Boulevard Adolphe Max Laan 118 126, Brussels, 1000 Belgium":
        "Boulevard Adolphe Max, Brussels, Belgium",
    "Bd Adolphe Max Laan 118 126, Brussels, 1000 Belgium":
        "Boulevard Adolphe Max, Brussels, Belgium",
    "Calle Fernández Vallín, 5, Gijon, 33205, ES":
        "Calle Fernández Vallín, Gijón, Spain",
    "C. de Castelar, 24, Casco Antiguo, 41001 Sevilla, Spain":
        "Casco Antiguo, Sevilla, Spain",
    "Paris Charles de Gaulle Airport":
        "Roissy-en-France, France",
    "College Green, Westmoreland Street, Dublin, 2 Ireland":
        "College Green, Dublin, Ireland",
    "at College Green, Westmoreland Street, Dublin, 2 Ireland":
        "College Green, Dublin, Ireland",
    "Crescent Rd - The Palm Jumeirah - Dubai - United Arab Emirates":
        "Palm Jumeirah, Dubai, United Arab Emirates",
    "DFDS\nAkershusstranda 31\n0150 Oslo\nNorway":
        "Akershusstranda 31, Oslo, Norway",
    "DFDS Akershusstranda 31 0150 Oslo Norway":
        "Akershusstranda 31, Oslo, Norway",
    "Gamle Landevej 39, 9990 Skagen, Denmark":
        "Skagen, Denmark",
    "Hazza Bin Zayed Street Al Wahda Complex - Al Nahyan - E19 - Abu Dhabi - United Arab Emirates":
        "Al Wahda, Abu Dhabi, United Arab Emirates",
    "Hazza Bin Zayed Street Al Wahda Complex - Al Nahyan - Zone 1 - Abu Dhabi - United Arab Emirates":
        "Al Wahda, Abu Dhabi, United Arab Emirates",
    "Jl Petitenget DENPASAR ID 80361":
        "Petitenget, Seminyak, Bali, Indonesia",
    "Kawasan Pariwisata Nusa Dua NUSA DUA ID 80363":
        "Nusa Dua, Bali, Indonesia",
    "Kriegersvej 27, 31, 8000 Aarhus C, Denmark":
        "Kriegersvej, Aarhus, Denmark",
    "Le Bourg\n14430 Beuvron-en-Auge\nFrance":
        "Beuvron-en-Auge, France",
    "Le Bourg 14430 Beuvron-en-Auge France":
        "Beuvron-en-Auge, France",
    "Marqués de Casa Valdés, 8, Gijón, 33202, Spain":
        "Gijón, Spain",
    "Punta Nizuc, Hotel Zone, 77500 Cancún, Quintana Roo, Mexico":
        "Punta Nizuc, Cancún, Mexico",
    "Raadhuspladsen 57, Copenhagen, 1550, Denmark":
        "Rådhuspladsen, Copenhagen, Denmark",
    "Opposite Circuit House, Sevagram, Khajuraho, Madhya Pradesh 471606, India":
        "Khajuraho, Madhya Pradesh, India",
    "Strada Micurà De Ru, 20, 39030 San Cassiano in Badia BZ, Italy\n+39 0471 849500 rosalpina.it":
        "San Cassiano, Badia, South Tyrol, Italy",
    "Strada Micurà De Ru, 20, 39030 San Cassiano in Badia BZ, Italy rosalpina.it":
        "San Cassiano, Badia, South Tyrol, Italy",
    "Strada Micurà De Ru, 20, 39030 San Cassiano in Badia BZ, Italy":
        "San Cassiano, Badia, South Tyrol, Italy",
    "Ulica Fausta Vrančića 12 10410 Velika Gorica, Croatia":
        "Velika Gorica, Croatia",
    "Via Alpe Di Grual 16 PINZOLO IT 38086":
        "Pinzolo, Trentino, Italy",
    "route de Palombaggia, BP 93, Porto-Vecchio, 20538, FR":
        "Palombaggia, Porto-Vecchio, Corsica, France",
}


def clean_query(query: str) -> str | None:
    """Apply cleaning rules to a geocode query. Returns None to delete the entry."""
    # Check manual overrides first (try raw, then whitespace-normalized)
    if query in MANUAL_OVERRIDES:
        return MANUAL_OVERRIDES[query]

    q = query

    # Remove newlines and collapse whitespace
    q = re.sub(r"\s+", " ", q).strip()

    # Check overrides again after normalization
    if q in MANUAL_OVERRIDES:
        return MANUAL_OVERRIDES[q]

    # Remove phone numbers (patterns like +39 0471 849500 or 33 8 92700210)
    q = re.sub(r"\+?\d[\d\s]{7,}", "", q).strip()

    # Remove URLs (e.g. rosalpina.it)
    q = re.sub(r"\s*\S+\.\w{2,3}\s*$", "", q).strip()

    # Check overrides again after phone/URL cleanup
    if q in MANUAL_OVERRIDES:
        return MANUAL_OVERRIDES[q]

    # Remove booking/flight info after colons with flight codes
    # e.g. "JFK:AF 6:CDG (OUT)" or "30 W 63RD ST : 30 W 63 St ..."
    if re.match(r"[A-Z]{3}:[A-Z]{2}\s+\d+:", q):
        return None  # flight route, not a real address

    # Strip "LABEL: actual address" prefixes (e.g. "30 W 63RD ST: 30 W 63 St ...")
    colon_match = re.match(r"^.{5,}?:\s*(\d+\s+.+)$", q)
    if colon_match:
        q = colon_match.group(1)

    # Remove parenthetical cross-street info: "(Broadway / Columbus Ave)"
    q = re.sub(r"\s*\([^)]*(?:\/|&)[^)]*\)\s*", " ", q).strip()

    # Remove "~ (See Event Details...)" type noise
    q = re.sub(r"\s*~\s*\(.*?\)\s*", " ", q).strip()

    # Remove apartment/unit numbers: "Apt.26CD", "#201"
    q = re.sub(r"\s*(?:Apt\.?\s*\S+|#\d+\w*)\s*", " ", q).strip()

    # Remove "Intersection Of ..." descriptions
    q = re.sub(r",?\s*Intersection Of[^,]*", "", q, flags=re.IGNORECASE).strip()

    # Remove "Entrance: ..." descriptions
    q = re.sub(r",?\s*Entrance:\s*\S+", "", q, flags=re.IGNORECASE).strip()

    # Remove "Rt. 50 East" style route descriptions within addresses
    q = re.sub(r",?\s*Rt\.\s*\d+\s*\w*\s+", " ", q).strip()

    # Strip "United States of America" → "USA" (Nominatim handles "USA" better)
    q = q.replace("United States of America", "USA")

    # Remove duplicate city/state after zip when already present
    # e.g. "1100 N Mathilda Ave, Sunnyvale, CA 94089 USA, Sunnyvale, CA, 94089"
    # Strategy: if a city name appears twice, drop everything after the zip
    zip_dup = re.match(
        r"(.+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*(?:USA?)?)\s*,\s*.+", q
    )
    if zip_dup:
        q = zip_dup.group(1).strip().rstrip(",")

    # Replace 2-letter country codes at end of address
    # Match ", XX" at the end where XX is a known code
    m = re.match(r"^(.+),\s*([A-Z]{2})$", q)
    if m and m.group(2) in COUNTRY_CODES:
        q = f"{m.group(1)}, {COUNTRY_CODES[m.group(2)]}"

    # Also handle "CITY XX ZIPCODE" patterns like "PINZOLO IT 38086"
    m2 = re.search(r"\b([A-Z]{2})\s+\d{4,6}\s*$", q)
    if m2 and m2.group(1) in COUNTRY_CODES:
        q = re.sub(
            r"\b[A-Z]{2}\s+\d{4,6}\s*$",
            COUNTRY_CODES[m2.group(1)],
            q,
        )

    # Handle "DENPASAR ID 80361" → "DENPASAR, Indonesia"
    # Already covered by the above rule

    # Clean "- " separated parts that look like regions (common in UAE/Dubai addresses)
    # e.g. "Al Sa'Diyat - Abu Dhabi - United Arab Emirates"
    # These are fine as-is after other cleanup, but let's replace " - " with ", "
    if " - " in q:
        q = q.replace(" - ", ", ")

    # Handle PO Box removal
    q = re.sub(r"\s*(?:PO\s*)?Box\s*\d+\.?\s*", " ", q, flags=re.IGNORECASE).strip()

    # Handle postal codes with spaces like "G1K 4C9" in Canadian addresses
    # These are fine, but clean up surrounding dashes
    q = re.sub(r"\s*-\s*([A-Z]\d[A-Z]\s*\d[A-Z]\d)\s*-\s*", r", \1, ", q)

    # Remove "TKCA 1ZZ" style postal codes (Turks and Caicos)
    q = re.sub(r"\s*TKCA\s+\d[A-Z]{2}\s*", " ", q).strip()

    # Remove transport descriptions like "Airport, Delta Airlines 219 Outside..."
    airport_match = re.match(
        r"((?:JFK|LGA|EWR|LAX)\s+Airport).*", q, flags=re.IGNORECASE
    )
    if airport_match:
        airport_name = airport_match.group(1)
        q = {
            "JFK Airport": "JFK Airport, New York, NY, USA",
            "LGA Airport": "LaGuardia Airport, New York, NY, USA",
            "EWR Airport": "Newark Airport, Newark, NJ, USA",
            "LAX Airport": "LAX Airport, Los Angeles, CA, USA",
        }.get(airport_name, airport_name)

    # "LaGuardia Airport Westjet" → just the airport
    if re.match(r"LaGuardia Airport\b", q):
        q = "LaGuardia Airport, New York, NY, USA"

    # Remove leading "at " (e.g. "at College Green, ...")
    q = re.sub(r"^at\s+", "", q, flags=re.IGNORECASE)

    # Remove "Opposite ..., " style prefixes
    q = re.sub(r"^Opposite\s+[^,]*,\s*", "", q, flags=re.IGNORECASE)

    # Remove "(COUNTRY)" suffix, e.g. "BEAUNE (FRANCE)"
    q = re.sub(r"\s*\(([A-Z]+)\)\s*$", lambda m: ", " + m.group(1).title(), q)

    # Remove "s/n" (sin número) from Spanish addresses
    q = re.sub(r",\s*s/n,", ",", q)

    # Expand "C." → "Calle" in Spanish addresses (helps Nominatim)
    if re.match(r"^C\.\s", q):
        q = "Calle" + q[2:]

    # Remove "Bd " / "Bld " prefix weirdness — Nominatim prefers "Boulevard"
    q = re.sub(r"^Bd\s+", "Boulevard ", q)
    q = re.sub(r"^Bld\s+", "Boulevard ", q)

    # Clean up stray commas and whitespace
    q = re.sub(r"\s*,\s*,+\s*", ", ", q)
    q = re.sub(r"\s{2,}", " ", q)
    q = q.strip(" ,")

    # If nothing useful remains
    if len(q) < 3:
        return None

    return q


def main():
    dry_run = "--dry-run" in sys.argv
    conn = get_connection()

    rows = conn.execute("""
        SELECT id, geocode_query FROM visited_locations
        WHERE lat IS NULL OR lng IS NULL
    """).fetchall()

    updated = 0
    deleted = 0
    unchanged = 0

    for row in rows:
        loc_id = row["id"]
        original = row["geocode_query"]
        cleaned = clean_query(original)

        if cleaned is None:
            if dry_run:
                print(f"DELETE: {original}")
            else:
                conn.execute("DELETE FROM visited_locations WHERE id=?", (loc_id,))
            deleted += 1
        elif cleaned != original:
            if dry_run:
                print(f"UPDATE: {original}")
                print(f"     -> {cleaned}")
            else:
                # Reset lat/lng so geocoder picks it up
                conn.execute(
                    "UPDATE visited_locations SET geocode_query=?, lat=NULL, lng=NULL WHERE id=?",
                    (cleaned, loc_id),
                )
            updated += 1
        else:
            unchanged += 1

    if not dry_run:
        conn.commit()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Results:")
    print(f"  Updated: {updated}")
    print(f"  Deleted: {deleted}")
    print(f"  Unchanged: {unchanged}")

    conn.close()


if __name__ == "__main__":
    main()
