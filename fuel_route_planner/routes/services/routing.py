
"""Get driving routes using the public OSRM routing service."""

import requests
import time

# Add alongside your existing imports and constants.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GEOCODER_HEADERS = {
    "User-Agent": "FuelRoutePlannerAssessment/1.0 (route planning assessment)"
}

_GEOCODE_CACHE = {}
_LAST_GEOCODE_REQUEST = 0.0


OSRM_BASE_URL = "https://router.project-osrm.org/route/v1/driving"


def get_route(start_lat, start_lon, end_lat, end_lon):
    """
    Get a driving route between two coordinate pairs.

    Coordinates must be decimal latitude and longitude values.

    Returns:
        dict: Distance in miles, duration in minutes, route geometry,
              and the route's coordinates in [longitude, latitude] order.

    Raises:
        ValueError: If coordinates are invalid or no route is found.
        requests.RequestException: If the routing service fails.
    """
    coordinates = (start_lat, start_lon, end_lat, end_lon)

    try:
        start_lat, start_lon, end_lat, end_lon = map(
            float, coordinates
        )
    except (TypeError, ValueError):
        raise ValueError("All coordinates must be valid numbers.")

    if not (
        -90 <= start_lat <= 90
        and -90 <= end_lat <= 90
        and -180 <= start_lon <= 180
        and -180 <= end_lon <= 180
    ):
        raise ValueError("Coordinates are outside valid latitude/longitude ranges.")

    url = (
        f"{OSRM_BASE_URL}/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
    )

    response = requests.get(
        url,
        params={
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("No driving route was found between these locations.")

    route = data["routes"][0]
    geometry = route["geometry"]

    return {
        "distance_miles": route["distance"] / 1609.344,
        "duration_minutes": route["duration"] / 60,
        "geometry": geometry,
        "coordinates": geometry["coordinates"],
    }

def geocode_location(location):
    """Convert a US address or city/state string into coordinates."""

    global _LAST_GEOCODE_REQUEST

    if not isinstance(location, str) or not location.strip():
        raise ValueError("Location must be a non-empty string.")

    location = location.strip()

    if location.casefold() in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[location.casefold()]

    # Respect the public Nominatim service's request-rate guidance.
    elapsed = time.monotonic() - _LAST_GEOCODE_REQUEST
    if _LAST_GEOCODE_REQUEST and elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": location,
            "countrycodes": "us",
            "format": "jsonv2",
            "limit": 1,
        },
        headers=GEOCODER_HEADERS,
        timeout=20,
    )
    _LAST_GEOCODE_REQUEST = time.monotonic()
    response.raise_for_status()

    results = response.json()

    if not results:
        raise ValueError(
            f"Could not find a US location matching '{location}'. "
            "Try including the state, for example 'Dallas, TX'."
        )

    result = (
        float(results[0]["lat"]),
        float(results[0]["lon"]),
    )

    _GEOCODE_CACHE[location.casefold()] = result
    return result
