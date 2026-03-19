#!/usr/bin/env python3
"""Build a static HTML map visualization from the trips database."""

import json

from db import get_connection, init_db

OUTPUT_FILE = "data/trips_map.html"


def load_trip_data(conn):
    """Load trip data with flight routes from the database.

    Each trip can appear at multiple locations: its primary_location plus
    any visited locations extracted from flights, lodging, activities, etc.
    """
    trips = conn.execute("""
        SELECT uuid, name, primary_location, start_date, end_date, lat, lng
        FROM trips
        WHERE start_date IS NOT NULL
        ORDER BY start_date
    """).fetchall()

    entries = []
    for t in trips:
        # Get unique flight routes for this trip
        flights = conn.execute("""
            SELECT DISTINCT origin, origin_name, destination, destination_name,
                   airline, flight_number
            FROM flights
            WHERE trip_uuid=?
        """, (t["uuid"],)).fetchall()

        routes = [
            {
                "from": f["origin_name"] or f["origin"] or "",
                "to": f["destination_name"] or f["destination"] or "",
                "airline": f["airline"] or "",
                "flight": f["flight_number"] or "",
            }
            for f in flights
        ]

        # Collect all geocoded locations for this trip
        visited = conn.execute("""
            SELECT name, lat, lng FROM visited_locations
            WHERE trip_uuid=? AND lat IS NOT NULL AND lng IS NOT NULL
        """, (t["uuid"],)).fetchall()

        # Use visited locations if available, otherwise fall back to primary
        seen_coords = set()
        if visited:
            for v in visited:
                coord_key = (round(v["lat"], 4), round(v["lng"], 4))
                if coord_key in seen_coords:
                    continue
                seen_coords.add(coord_key)
                entries.append({
                    "name": t["name"],
                    "location": v["name"],
                    "lat": v["lat"],
                    "lng": v["lng"],
                    "year": int(t["start_date"][:4]),
                    "start": t["start_date"],
                    "end": t["end_date"] or "",
                    "routes": routes,
                })

        # Always include primary_location if geocoded and not already covered
        if t["lat"] is not None and t["lng"] is not None:
            coord_key = (round(t["lat"], 4), round(t["lng"], 4))
            if coord_key not in seen_coords:
                entries.append({
                    "name": t["name"],
                    "location": t["primary_location"],
                    "lat": t["lat"],
                    "lng": t["lng"],
                    "year": int(t["start_date"][:4]),
                    "start": t["start_date"],
                    "end": t["end_date"] or "",
                    "routes": routes,
                })

    return entries


def generate_html(trip_data):
    years = sorted(set(t["year"] for t in trip_data))

    # Generate color palette for years
    year_colors = {}
    n = len(years)
    for i, y in enumerate(years):
        hue = int(360 * i / n)
        year_colors[y] = hue

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>My Travel Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }}

  header {{
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid #1e293b;
    flex-shrink: 0;
    z-index: 1000;
  }}

  header h1 {{
    font-size: 1.4rem;
    font-weight: 700;
    background: linear-gradient(135deg, #38bdf8, #818cf8, #c084fc);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.02em;
  }}

  .stats {{
    display: flex;
    gap: 24px;
    font-size: 0.85rem;
    color: #94a3b8;
  }}

  .stats span {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}

  .stats .num {{
    color: #e2e8f0;
    font-weight: 600;
    font-size: 1.1rem;
  }}

  .controls {{
    background: #1e293b;
    padding: 12px 24px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
    z-index: 1000;
  }}

  .controls label {{
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
    margin-right: 4px;
  }}

  .year-btn {{
    padding: 4px 12px;
    border-radius: 20px;
    border: 2px solid transparent;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    background: #334155;
    color: #94a3b8;
  }}

  .year-btn:hover {{
    background: #475569;
    color: #e2e8f0;
  }}

  .year-btn.active {{
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.3);
  }}

  .meta-btn {{
    padding: 4px 14px;
    border-radius: 20px;
    border: 2px solid #475569;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    background: transparent;
    color: #94a3b8;
  }}

  .meta-btn:hover {{
    border-color: #818cf8;
    color: #e2e8f0;
  }}

  .meta-btn.active {{
    border-color: #818cf8;
    background: #818cf8;
    color: #fff;
  }}

  #map {{
    flex: 1;
    z-index: 1;
  }}

  .trip-popup {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  }}

  .trip-popup h3 {{
    font-size: 1rem;
    font-weight: 700;
    color: #1e293b;
    margin-bottom: 4px;
  }}

  .trip-popup .loc {{
    font-size: 0.85rem;
    color: #64748b;
    margin-bottom: 6px;
  }}

  .trip-popup .dates {{
    font-size: 0.8rem;
    color: #475569;
    margin-bottom: 6px;
  }}

  .trip-popup .routes {{
    font-size: 0.75rem;
    color: #64748b;
    border-top: 1px solid #e2e8f0;
    padding-top: 6px;
    margin-top: 4px;
  }}

  .trip-popup .route {{
    margin: 2px 0;
  }}

  .leaflet-popup-content-wrapper {{
    border-radius: 12px !important;
    box-shadow: 0 10px 40px rgba(0,0,0,0.2) !important;
  }}

  .leaflet-popup-content {{
    margin: 14px 16px !important;
  }}

  .location-cluster {{
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 0.75rem;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0,0,0,0.3);
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    border: 2px solid rgba(255,255,255,0.4);
  }}
</style>
</head>
<body>

<header>
  <h1>Travel Map</h1>
  <div class="stats">
    <span><span class="num" id="trip-count">0</span> trips</span>
    <span><span class="num" id="location-count">0</span> places</span>
    <span><span class="num" id="country-count">0</span> countries</span>
  </div>
</header>

<div class="controls">
  <label>Filter</label>
  <button class="meta-btn active" onclick="toggleAll()">All</button>
  <button class="meta-btn" onclick="selectNone()">None</button>
  <span style="width:8px"></span>
  {"".join(f'<button class="year-btn" data-year="{y}" onclick="toggleYear({y})">{y}</button>' for y in years)}
</div>

<div id="map"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const TRIPS = {json.dumps(trip_data)};

const YEAR_HUES = {json.dumps(year_colors)};

function yearColor(year, alpha) {{
  const h = YEAR_HUES[year] || 200;
  return `hsla(${{h}}, 70%, 55%, ${{alpha || 1}})`;
}}

function yearColorSolid(year) {{
  const h = YEAR_HUES[year] || 200;
  return `hsl(${{h}}, 70%, 55%)`;
}}

// State
let activeYears = new Set({json.dumps(years)});
let markers = [];
let map;

function initMap() {{
  map = L.map('map', {{
    zoomControl: true,
    attributionControl: true,
  }}).setView([30, 0], 3);

  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
  }}).addTo(map);

  renderMarkers();
  updateButtons();
  updateStats();
}}

function renderMarkers() {{
  markers.forEach(m => map.removeLayer(m));
  markers = [];

  const byLocation = {{}};
  TRIPS.forEach(t => {{
    if (!activeYears.has(t.year)) return;
    const key = t.lat + ',' + t.lng;
    if (!byLocation[key]) byLocation[key] = [];
    byLocation[key].push(t);
  }});

  Object.entries(byLocation).forEach(([key, trips]) => {{
    const lat = trips[0].lat;
    const lng = trips[0].lng;
    const count = trips.length;

    const yearCounts = {{}};
    trips.forEach(t => {{ yearCounts[t.year] = (yearCounts[t.year] || 0) + 1; }});

    let marker;
    if (count === 1) {{
      const t = trips[0];
      marker = L.circleMarker([lat, lng], {{
        radius: 7,
        fillColor: yearColorSolid(t.year),
        fillOpacity: 0.9,
        color: '#fff',
        weight: 2,
        opacity: 0.7,
      }});
    }} else {{
      const size = Math.min(18 + count * 3, 40);
      const uniqueYears = [...new Set(trips.map(t => t.year))].sort();

      if (uniqueYears.length === 1) {{
        marker = L.circleMarker([lat, lng], {{
          radius: size / 2,
          fillColor: yearColorSolid(uniqueYears[0]),
          fillOpacity: 0.9,
          color: '#fff',
          weight: 2,
          opacity: 0.7,
        }});
      }} else {{
        const sorted = uniqueYears.sort((a, b) => b - a);
        marker = L.circleMarker([lat, lng], {{
          radius: size / 2,
          fillColor: yearColorSolid(sorted[0]),
          fillOpacity: 0.85,
          color: yearColorSolid(sorted[sorted.length - 1]),
          weight: 3,
          opacity: 0.8,
        }});
      }}

      const icon = L.divIcon({{
        className: 'location-cluster',
        html: `<div style="
          width:${{size}}px;height:${{size}}px;
          border-radius:50%;
          display:flex;align-items:center;justify-content:center;
          font-size:${{size > 24 ? 12 : 10}}px;
          font-weight:700;color:#fff;
          pointer-events:none;
        ">${{count}}</div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      }});
      const label = L.marker([lat, lng], {{ icon, interactive: false }}).addTo(map);
      markers.push(label);
    }}

    const popupHtml = trips.map(t => {{
      let html = `<div class="trip-popup">
        <h3>${{t.name}}</h3>
        <div class="loc">${{t.location}}</div>
        <div class="dates">
          <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${{yearColorSolid(t.year)}};margin-right:4px;vertical-align:middle;"></span>
          ${{formatDate(t.start)}} — ${{formatDate(t.end)}}
        </div>`;
      if (t.routes.length > 0) {{
        html += `<div class="routes">`;
        t.routes.forEach(r => {{
          html += `<div class="route">✈ ${{r.flight}} · ${{r.from.split(' (')[0]}} → ${{r.to.split(' (')[0]}}</div>`;
        }});
        html += `</div>`;
      }}
      html += `</div>`;
      return html;
    }}).join('<hr style="border:none;border-top:1px solid #e2e8f0;margin:8px 0;">');

    marker.bindPopup(popupHtml, {{ maxWidth: 350, maxHeight: 300 }});
    marker.addTo(map);
    markers.push(marker);
  }});
}}

function formatDate(d) {{
  if (!d) return '';
  const [y, m, day] = d.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${{months[parseInt(m)-1]}} ${{parseInt(day)}}, ${{y}}`;
}}

function toggleYear(year) {{
  if (activeYears.has(year)) {{
    activeYears.delete(year);
  }} else {{
    activeYears.add(year);
  }}
  renderMarkers();
  updateButtons();
  updateStats();
}}

function toggleAll() {{
  const years = Object.keys(YEAR_HUES).map(Number);
  if (activeYears.size === years.length) {{
    activeYears.clear();
  }} else {{
    years.forEach(y => activeYears.add(y));
  }}
  renderMarkers();
  updateButtons();
  updateStats();
}}

function selectNone() {{
  activeYears.clear();
  renderMarkers();
  updateButtons();
  updateStats();
}}

function updateButtons() {{
  document.querySelectorAll('.year-btn').forEach(btn => {{
    const year = parseInt(btn.dataset.year);
    const isActive = activeYears.has(year);
    btn.classList.toggle('active', isActive);
    if (isActive) {{
      btn.style.background = yearColorSolid(year);
      btn.style.borderColor = yearColorSolid(year);
      btn.style.color = '#fff';
    }} else {{
      btn.style.background = '#334155';
      btn.style.borderColor = 'transparent';
      btn.style.color = '#94a3b8';
    }}
  }});

  const allYears = Object.keys(YEAR_HUES).map(Number);
  const allBtn = document.querySelectorAll('.meta-btn')[0];
  allBtn.classList.toggle('active', activeYears.size === allYears.length);

  const noneBtn = document.querySelectorAll('.meta-btn')[1];
  noneBtn.classList.toggle('active', activeYears.size === 0);
}}

function updateStats() {{
  const visible = TRIPS.filter(t => activeYears.has(t.year));
  document.getElementById('trip-count').textContent = visible.length;

  const places = new Set(visible.map(t => t.location));
  document.getElementById('location-count').textContent = places.size;

  const countries = new Set(visible.map(t => {{
    const parts = t.location.split(', ');
    return parts[parts.length - 1];
  }}));
  document.getElementById('country-count').textContent = countries.size;
}}

initMap();
</script>
</body>
</html>"""
    return html


def main():
    conn = get_connection()
    init_db(conn)

    print("Loading trips from database...")
    trip_data = load_trip_data(conn)
    conn.close()

    if not trip_data:
        print("No geocoded trips found. Run the exporter and geocoder first.")
        return

    print(f"Found {len(trip_data)} trips across {len(set(t['location'] for t in trip_data))} locations")
    print("Generating HTML...")
    html = generate_html(trip_data)

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)

    print(f"Done! Open {OUTPUT_FILE} in your browser.")


if __name__ == "__main__":
    main()
