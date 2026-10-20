
"""Django API views for fuel route planning."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from routes.services.fuel_calculator import calculate_fuel_plan
from routes.services.fuel_prices import load_fuel_prices
from routes.services.routing import get_route, geocode_location


@csrf_exempt
@require_POST
def plan_route(request):
    """Plan a US driving route and estimate fuel stops and cost."""

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"error": "Request body must contain valid JSON."},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"error": "JSON body must be an object."},
            status=400,
        )

    start_location = payload.get("start_location")
    finish_location = payload.get("finish_location")

    if not start_location or not finish_location:
        return JsonResponse(
            {
                "error": (
                    "Both 'start_location' and 'finish_location' "
                    "are required."
                )
            },
            status=400,
        )

    try:
        # Resolve city/address inputs to coordinates.
        start_lat, start_lon = geocode_location(start_location)
        end_lat, end_lon = geocode_location(finish_location)

        route = get_route(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
        )

        fuel_prices = load_fuel_prices(only_us=True)

        plan = calculate_fuel_plan(
            route=route,
            fuel_prices=fuel_prices,
            mpg=10,
            range_miles=500,
            safety_margin_miles=50,
            corridor_miles=10,
        )

        return JsonResponse(
            {
                "start_location": start_location,
                "finish_location": finish_location,
                "start_coordinates": {
                    "latitude": start_lat,
                    "longitude": start_lon,
                },
                "finish_coordinates": {
                    "latitude": end_lat,
                    "longitude": end_lon,
                },
                "route": {
                    "distance_miles": round(
                        route["distance_miles"], 2
                    ),
                    "duration_minutes": round(
                        route["duration_minutes"], 2
                    ),
                    "geometry": route["geometry"],
                },
                "vehicle": {
                    "range_miles": 500,
                    "mpg": 10,
                    "assumed_starting_fuel": "Full tank",
                },
                "fuel_plan": plan,
                "data_note": (
                    "Fuel prices come from the supplied assessment CSV "
                    "and may not reflect current prices."
                ),
            },
            status=200,
        )

    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except FileNotFoundError as error:
        return JsonResponse({"error": str(error)}, status=500)
    except Exception:
        # Log the exception in a production application rather than
        # returning internal error details to API clients.
        return JsonResponse(
            {
                "error": (
                    "Route planning failed. Check the geocoding/routing "
                    "service and server logs, then try again."
                )
            },
            status=502,
        )
