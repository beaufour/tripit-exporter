#!/usr/bin/env python3
"""Build a static HTML map visualization from trips.json."""

import json
import time
import os
from geopy.geocoders import Nominatim

TRIPS_FILE = "trips.json"
GEOCACHE_FILE = "geocache.json"
OUTPUT_FILE = "trips_map.html"


def load_geocache():
    if os.path.exists(GEOCACHE_FILE):
        with open(GEOCACHE_FILE) as f:
            return json.load(f)
    return {}


def save_geocache(cache):
    with open(GEOCACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def geocode_locations(locations):
    cache = load_geocache()
    geolocator = Nominatim(user_agent="tripit-map-builder")
    for loc in sorted(locations):
        if loc in cache:
            continue
        print(f"  Geocoding: {loc}")
        try:
            result = geolocator.geocode(loc, timeout=10)
            if result:
                cache[loc] = {"lat": result.latitude, "lng": result.longitude}
            else:
                print(f"    WARNING: Could not geocode '{loc}'")
                cache[loc] = None
            time.sleep(1.1)  # Nominatim rate limit
        except Exception as e:
            print(f"    ERROR geocoding '{loc}': {e}")
            cache[loc] = None
    save_geocache(cache)
    return cache


def build_trip_data(trips, geocache):
    """Build the JS data structure for the map."""
    entries = []
    for trip in trips:
        loc = trip.get("primary_location", "")
        coords = geocache.get(loc)
        if not coords:
            continue
        year = trip["start_date"][:4] if trip.get("start_date") else None
        if not year:
            continue

        # Collect flight routes
        routes = []
        if trip.get("flights"):
            seen = set()
            for f in trip["flights"]:
                key = (f.get("origin"), f.get("destination"))
                if key not in seen:
                    seen.add(key)
                    routes.append(
                        {
                            "from": f.get("origin_name", f.get("origin", "")),
                            "to": f.get("destination_name", f.get("destination", "")),
                            "airline": f.get("airline", ""),
                            "flight": f.get("flight_number", ""),
                        }
                    )

        entries.append(
            {
                "name": trip["name"],
                "location": loc,
                "lat": coords["lat"],
                "lng": coords["lng"],
                "year": int(year),
                "start": trip.get("start_date", ""),
                "end": trip.get("end_date", ""),
                "flights": len(trip.get("flights", [])),
                "routes": routes,
            }
        )
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

  /* Make Leaflet popups nicer */
  .leaflet-popup-content-wrapper {{
    border-radius: 12px !important;
    box-shadow: 0 10px 40px rgba(0,0,0,0.2) !important;
  }}

  .leaflet-popup-content {{
    margin: 14px 16px !important;
  }}

  /* Cluster styles */
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
  // Clear existing
  markers.forEach(m => map.removeLayer(m));
  markers = [];

  // Group trips by location
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

    // Determine dominant year (most trips) for color
    const yearCounts = {{}};
    trips.forEach(t => {{ yearCounts[t.year] = (yearCounts[t.year] || 0) + 1; }});

    // Create multi-ring marker for multiple years, single dot for one
    let marker;
    if (count === 1) {{
      const t = trips[0];
      const size = 14;
      marker = L.circleMarker([lat, lng], {{
        radius: size / 2,
        fillColor: yearColorSolid(t.year),
        fillOpacity: 0.9,
        color: '#fff',
        weight: 2,
        opacity: 0.7,
      }});
    }} else {{
      // Size based on trip count
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
        // Gradient-like effect: use the most recent year's color with a glow
        const sorted = uniqueYears.sort((a, b) => b - a);
        const mainColor = yearColorSolid(sorted[0]);
        marker = L.circleMarker([lat, lng], {{
          radius: size / 2,
          fillColor: mainColor,
          fillOpacity: 0.85,
          color: yearColorSolid(sorted[sorted.length - 1]),
          weight: 3,
          opacity: 0.8,
        }});
      }}

      // Add count label
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
      // Add a transparent div icon on top for the label
      const label = L.marker([lat, lng], {{ icon, interactive: false }}).addTo(map);
      markers.push(label);
    }}

    // Build popup
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
  const allBtn = document.querySelector('.meta-btn');
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
    print("Loading trips...")
    with open(TRIPS_FILE) as f:
        trips = json.load(f)

    locations = set(t["primary_location"] for t in trips if t.get("primary_location"))
    print(f"Found {len(trips)} trips across {len(locations)} unique locations")

    print("Geocoding locations...")
    geocache = geocode_locations(locations)

    failed = [loc for loc, coords in geocache.items() if coords is None and loc in locations]
    if failed:
        print(f"\nWARNING: Could not geocode {len(failed)} locations:")
        for loc in failed:
            print(f"  - {loc}")

    print("Building trip data...")
    trip_data = build_trip_data(trips, geocache)

    print("Generating HTML...")
    html = generate_html(trip_data)

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)

    print(f"\nDone! Open {OUTPUT_FILE} in your browser.")
    print(f"  {len(trip_data)} trips mapped across {len(set(t['location'] for t in trip_data))} locations")


if __name__ == "__main__":
    main()
