# Fuel Route Planner API

Django API that returns a US driving route, approximate cost-effective fuel stops, and estimated fuel cost using the supplied fuel-price file.

## Stack and external services
- Django **6.1.2** (latest stable at project creation)
- OSRM public demo server for road routing (one routing request per uncached request)
- OpenStreetMap Nominatim for start/end geocoding (two geocoding requests per uncached request)
- GeoNames city gazetteer (`geonamescache`) for approximate fuel-station city coordinates
- Fuel prices stored locally in `planner/data/fuel_prices.csv`

OSRM public demo and Nominatim are community services, not production SLAs. Respect the Nominatim usage policy, identify the application with a real User-Agent, cache repeat geocodes, and be prepared to switch providers. This implementation caches geocodes in-process; production should use a persistent cache (Redis/database) and configure rate limiting.

## Project structure

```text
Backend Django Engineer (Assessment)/
├── README.md
├── requirements.txt
└── fuel_route_planner/
    ├── db.sqlite3
    ├── manage.py
    └── main_config/
        ├── __init__.py
        ├── asgi.py
        ├── settings.py
        ├── urls.py
        └── wsgi.py
```

## Setup

Python 3.12+ recommended. Run these commands from the repository root—the folder containing `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\fuel_route_planner\manage.py migrate
python .\fuel_route_planner\manage.py runserver
```

## Endpoint
`POST http://127.0.0.1:8000/api/route-plan/`

JSON:
```json
{
  "start": "Austin, Texas, USA",
  "finish": "Dallas, Texas, USA"
}
```

Returns `distance_miles`, `estimated_fuel_gallons`, `estimated_total_fuel_cost_usd`, `fuel_stops`, and a GeoJSON `route_geometry` that can be rendered on a map (for example Leaflet). Errors return JSON with a 4xx/5xx status.

## Postman quick test
1. Method `POST`, URL `http://127.0.0.1:8000/api/route-plan/`
2. Body > raw > JSON; paste the request above.
3. Send. The first request may take longer while geocoding; repeated endpoint geocoding is cached for the life of the process.

## Fuel-price data limitations and optimization notes
The supplied file has station names, city/state, address text and price, but no latitude/longitude. The app matches city/state to a local GeoNames gazetteer and treats each station as located at its city coordinate. This is a deliberate zero-extra-geocoding-call trade-off, but means nearby stations in the same city may appear at the same approximate point. Some smaller cities may not be in the gazetteer; run `python manage.py check_data` to inspect coverage.

The dynamic-programming planner considers stations within 35 straight-line miles of the route, buckets candidates into 10-mile route segments, and chooses a low-cost sequence where no leg exceeds 500 miles. Since the input does not specify starting fuel level or station-level coordinates, total cost is an estimate under the assumptions returned by the API. A production-grade result should enrich the dataset with actual station coordinates and model starting fuel / tank capacity explicitly.

## API call count
For a cache-cold request: two Nominatim geocoding requests + one OSRM route request. Fuel stations are never individually geocoded. Geocodes are process-cached; use persistent caching for multi-worker deployments.

## Useful references
- Django downloads: https://www.djangoproject.com/download/
- OSRM HTTP API: https://project-osrm.org/docs/
- Nominatim usage policy: https://operations.osmfoundation.org/policies/nominatim/
