# Fuel Route Planner API

A Django API that returns a US driving route, suggested fuel stops, and estimated fuel costs using the supplied fuel-price dataset.

## Requirements

- Python 3.12 or later recommended
- Git
- Internet access for geocoding, routing, and map tiles

The API uses OpenStreetMap Nominatim for geocoding and the public OSRM demo server for routing. These community services can be slow or unavailable and are not intended to provide production service guarantees.

## Project structure

```text
Backend Django Engineer (Assessment)/
├── README.md
├── requirements.txt
└── fuel_route_planner/
    ├── manage.py
    ├── route-map.html
    ├── main_config/
    │   ├── __init__.py
    │   ├── asgi.py
    │   ├── settings.py
    │   ├── urls.py
    │   └── wsgi.py
    └── routes/
        ├── __init__.py
        ├── admin.py
        ├── apps.py
        ├── models.py
        ├── tests.py
        ├── urls.py
        ├── views.py
        ├── data/
        │   ├── fuel-prices-for-be-assessment.csv
        │   └── fuel-prices-with-coordinates.csv
        ├── migrations/
        │   └── __init__.py
        └── services/
            ├── __init__.py
            ├── city_coordinates.py
            ├── fuel_calculator.py
            ├── fuel_prices.py
            └── routing.py
```

The local SQLite database is created when you run migrations. Local environment files, the virtual environment, and Python cache files are not required in the repository.

## Setup

Run commands from the repository root—the folder containing `requirements.txt`.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\fuel_route_planner\manage.py migrate
python .\fuel_route_planner\manage.py check
python .\fuel_route_planner\manage.py runserver
```

If PowerShell blocks virtual-environment activation, use Git Bash instead.

### Windows Git Bash

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python fuel_route_planner/manage.py migrate
python fuel_route_planner/manage.py check
python fuel_route_planner/manage.py runserver
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python fuel_route_planner/manage.py migrate
python fuel_route_planner/manage.py check
python fuel_route_planner/manage.py runserver
```

The development server runs at `http://127.0.0.1:8000/`. Keep its terminal open while sending API requests.

## API

**Endpoint:** `POST http://127.0.0.1:8000/api/plan-route/`

**Content-Type:** `application/json`

Example request:

```json
{
  "start_location": "New York, NY",
  "finish_location": "Los Angeles, CA"
}
```

Example using `curl` from Git Bash, run from the `fuel_route_planner` directory:

```bash
curl -sS -X POST "http://127.0.0.1:8000/api/plan-route/" \
  -H "Content-Type: application/json" \
  -d '{"start_location":"New York, NY","finish_location":"Los Angeles, CA"}'
```

To save the JSON response to a local file instead of displaying the full route geometry in the terminal:

```bash
curl -sS -X POST "http://127.0.0.1:8000/api/plan-route/" \
  -H "Content-Type: application/json" \
  -d '{"start_location":"New York, NY","finish_location":"Los Angeles, CA"}' \
  -o route-response.txt
```

The response includes the resolved locations, route distance and geometry, vehicle assumptions, fuel plan, and a note about the supplied price data. Invalid JSON or missing required fields returns a JSON error response.

## Optional route map

The project includes `fuel_route_planner/route-map.html`, which can display the saved `route-response.txt` response on an interactive map.

After generating `route-response.txt`, open a second terminal, change to the `fuel_route_planner` directory, and start a local file server:

```bash
python -m http.server 8001
```

Then open `http://127.0.0.1:8001/route-map.html` in a browser. Keep the file server running while viewing the map. The map uses Leaflet and OpenStreetMap tiles, so the browser needs internet access.

## Tests

Run the Django checks and route-app tests from the repository root:

```bash
python fuel_route_planner/manage.py check
python fuel_route_planner/manage.py test routes
```

If already in the `fuel_route_planner` directory, use:

```bash
python manage.py check
python manage.py test routes
```

## Fuel data and estimate limitations

Fuel prices are loaded from `fuel_route_planner/routes/data/fuel-prices-with-coordinates.csv`. The file contains the supplied price data with added coordinates. Coordinates may approximate a station's city rather than its exact location, so route proximity and stop locations are estimates. Prices are from the supplied dataset and may not be current.

The planner assumes a 10 MPG vehicle and a full tank at departure. Its fuel-stop calculations are estimates based on the available station candidates and configured range/safety assumptions; they are not a guarantee of the globally cheapest real-world refueling plan. The API distinguishes estimated total trip fuel-consumption cost from estimated purchases made en route.

On a cache-cold request, the application makes up to two Nominatim geocoding requests and one OSRM routing request. Geocoded locations are cached in process memory; the cache is not shared across server workers or retained after restart.

## Development and production

`runserver` is Django's development server and is for local testing only. Do not deploy with development settings or the development secret key. Public Nominatim and OSRM demo services do not provide production SLAs; a production deployment should use suitable providers, persistent caching, rate limiting, and production Django settings.

## References

- [Django documentation](https://docs.djangoproject.com/)
- [OSRM API documentation](https://project-osrm.org/docs/)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [Leaflet documentation](https://leafletjs.com/)
