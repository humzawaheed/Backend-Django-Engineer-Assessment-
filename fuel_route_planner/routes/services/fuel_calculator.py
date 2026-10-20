
"""Select affordable fuel stops along a driving route."""

import math

import numpy as np
import pandas as pd


EARTH_RADIUS_MILES = 3958.7613



def _haversine_miles(lat, lon, coordinates):
    """Calculate distances from coordinates to one or more [lon, lat] points."""
    coordinates = np.asarray(coordinates, dtype=float)

    lat1 = np.radians(lat)
    lon1 = np.radians(lon)
    lat2 = np.radians(coordinates[..., 1])
    lon2 = np.radians(coordinates[..., 0])

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(lat1)
        * np.cos(lat2)
        * np.sin(delta_lon / 2) ** 2
    )

    a = np.clip(a, 0, 1)

    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def _find_route_candidates(
    route,
    fuel_prices,
    corridor_miles=10,
    candidates_per_25_miles=5,
):
    """Find stations near the route and estimate their route positions."""

    coordinates = route.get("coordinates", [])
    route_distance = float(route["distance_miles"])

    if len(coordinates) < 2:
        raise ValueError("Route geometry must contain at least two points.")

    # Sample the route to keep station matching reasonably fast.
    stride = max(1, len(coordinates) // 800)
    sampled = coordinates[::stride]

    if sampled[-1] != coordinates[-1]:
        sampled.append(coordinates[-1])

    sampled = np.asarray(sampled, dtype=float)

    segment_distances = _haversine_miles(
        sampled[:-1, 1],
        sampled[:-1, 0],
        sampled[1:],
    )

    cumulative = np.concatenate(([0.0], np.cumsum(segment_distances)))

    if cumulative[-1] <= 0:
        raise ValueError("Could not calculate route geometry distances.")

    # Scale sampled geometry distances to OSRM's reported route distance.
    cumulative *= route_distance / cumulative[-1]

    stations = fuel_prices.copy()
    stations["Latitude"] = pd.to_numeric(
        stations["Latitude"], errors="coerce"
    )
    stations["Longitude"] = pd.to_numeric(
        stations["Longitude"], errors="coerce"
    )

    stations = stations.dropna(
        subset=["Latitude", "Longitude", "Retail Price"]
    ).copy()

    stations = stations[
        stations["Latitude"].between(-90, 90)
        & stations["Longitude"].between(-180, 180)
    ].copy()

    candidate_records = []

    for row in stations.to_dict("records"):
        distances = _haversine_miles(
            float(row["Latitude"]),
            float(row["Longitude"]),
            sampled,
        )

        nearest_index = int(np.argmin(distances))
        off_route = float(distances[nearest_index])

        if off_route > corridor_miles:
            continue

        progress = float(cumulative[nearest_index])

        # Do not recommend stations at the trip's endpoints.
        if progress <= 1 or progress >= route_distance - 1:
            continue

        row["Distance From Route Miles"] = round(off_route, 2)
        row["Route Progress Miles"] = round(progress, 2)
        candidate_records.append(row)

    if not candidate_records:
        return pd.DataFrame()

    candidates = pd.DataFrame(candidate_records)

    # Keep several affordable choices in each route section.
    # This limits computation without collapsing the source dataset.
    candidates["Route Section"] = (
        candidates["Route Progress Miles"] // 25
    ).astype(int)

    candidates = candidates.sort_values(
        ["Retail Price", "Distance From Route Miles"]
    )

    candidates = (
        candidates.groupby("Route Section", group_keys=False)
        .head(candidates_per_25_miles)
        .sort_values("Route Progress Miles")
        .reset_index(drop=True)
    )

    return candidates


def calculate_fuel_plan(
    route,
    fuel_prices,
    mpg=10,
    range_miles=500,
    safety_margin_miles=50,
    corridor_miles=10,
):
    """
    Estimate trip fuel cost and select affordable, reachable fuel stops.

    Assumptions:
    - The vehicle starts with a full tank.
    - MPG and range are provided by the assessment.
    - Candidate stations must be within corridor_miles of the route.
    - Stops are planned with a safety margin for trips over vehicle range.
    - Costs use the supplied dataset, not live fuel prices.
    """

    if mpg <= 0:
        raise ValueError("mpg must be greater than zero.")

    if range_miles <= 0:
        raise ValueError("range_miles must be greater than zero.")

    if not 0 <= safety_margin_miles < range_miles:
        raise ValueError(
            "Safety margin must be non-negative and less than vehicle range."
        )

    route_distance = float(route["distance_miles"])
    total_gallons = route_distance / mpg

    if fuel_prices.empty:
        raise ValueError("No fuel-price records are available.")

    candidates = _find_route_candidates(
        route,
        fuel_prices,
        corridor_miles=corridor_miles,
    )

    # A full tank can reach the destination: do not force a stop.
    if route_distance <= range_miles:
        if not candidates.empty:
            reference_price = float(candidates["Retail Price"].mean())
            price_basis = (
                "Average listed price of stations near the route; "
                "no en-route refueling is required."
            )
        else:
            reference_price = float(fuel_prices["Retail Price"].mean())
            price_basis = (
                "Dataset-wide average price; no suitable route stations "
                "were found for a local estimate."
            )

        return {
            "route_distance_miles": round(route_distance, 2),
            "estimated_fuel_gallons": round(total_gallons, 2),
            "estimated_fuel_cost": round(
                total_gallons * reference_price, 2
            ),
            "estimated_cost_basis": price_basis,
            "refueling_required": False,
            "stops": [],
            "message": (
                "The destination is within the assumed full-tank range."
            ),
        }

    if candidates.empty:
        return {
            "route_distance_miles": round(route_distance, 2),
            "estimated_fuel_gallons": round(total_gallons, 2),
            "estimated_fuel_cost": None,
            "estimated_cost_basis": (
                "No feasible plan: no fuel stations were found within "
                f"{corridor_miles} miles of the route."
            ),
            "refueling_required": True,
            "stops": [],
            "message": (
                "No suitable fuel stations were found near the route. "
                "Try a wider route corridor or check the dataset."
            ),
        }

    # Build nodes: start, candidate stations, and destination.
    station_nodes = candidates.to_dict("records")

    nodes = [{
        "kind": "start",
        "progress": 0.0,
        "off_route": 0.0,
    }]

    for station in station_nodes:
        nodes.append({
            "kind": "station",
            "progress": float(station["Route Progress Miles"]),
            "off_route": float(station["Distance From Route Miles"]),
            "station": station,
        })

    nodes.append({
        "kind": "destination",
        "progress": route_distance,
        "off_route": 0.0,
    })

    nodes.sort(key=lambda node: node["progress"])

    start_index = next(
        i for i, node in enumerate(nodes) if node["kind"] == "start"
    )
    destination_index = next(
        i for i, node in enumerate(nodes)
        if node["kind"] == "destination"
    )

    # Only allow planned legs up to 450 miles by default,
    # leaving a 50-mile safety margin on a 500-mile range.
    max_leg_miles = range_miles - safety_margin_miles
    count = len(nodes)

    best_cost = [float("inf")] * count
    previous = [None] * count
    best_cost[start_index] = 0.0

    for j in range(start_index + 1, destination_index + 1):
        current = nodes[j]

        for i in range(start_index, j):
            if not math.isfinite(best_cost[i]):
                continue

            prior = nodes[i]
            leg_distance = (
                current["progress"]
                - prior["progress"]
                + prior["off_route"]
                + current["off_route"]
            )

            if leg_distance <= 0 or leg_distance > max_leg_miles:
                continue

            # The first leg is priced using the first stop.
            # Later legs are priced using the station departed from.
            if prior["kind"] == "start":
                if current["kind"] != "station":
                    continue
                price = float(current["station"]["Retail Price"])
            else:
                price = float(prior["station"]["Retail Price"])

            leg_cost = (leg_distance / mpg) * price
            proposed_cost = best_cost[i] + leg_cost

            if proposed_cost < best_cost[j]:
                best_cost[j] = proposed_cost
                previous[j] = i

    if not math.isfinite(best_cost[destination_index]):
        return {
            "route_distance_miles": round(route_distance, 2),
            "estimated_fuel_gallons": round(total_gallons, 2),
            "estimated_fuel_cost": None,
            "estimated_cost_basis": (
                "No feasible plan within the configured range and safety "
                "margin using the available route stations."
            ),
            "refueling_required": True,
            "stops": [],
            "message": (
                "A safe fuel-stop plan could not be found. Try widening "
                "the route corridor or reviewing missing station data."
            ),
        }

    # Reconstruct the cheapest feasible station sequence.
    path_indices = []
    current_index = destination_index

    while current_index != start_index:
        current_index = previous[current_index]

        if current_index is None:
            raise RuntimeError("Failed to reconstruct fuel-stop plan.")

        if nodes[current_index]["kind"] == "station":
            path_indices.append(current_index)

    path_indices.reverse()

    selected_stops = []
    previous_node = nodes[start_index]

    for index in path_indices:
        node = nodes[index]
        station = node["station"]

        leg_distance = (
            node["progress"]
            - previous_node["progress"]
            + previous_node["off_route"]
            + node["off_route"]
        )

        # Price estimate for the leg ending at this stop.
        # For the initial leg, this is the arriving station's price.
        if previous_node["kind"] == "start":
            leg_price = float(station["Retail Price"])
        else:
            leg_price = float(
                previous_node["station"]["Retail Price"]
            )

        selected_stops.append({
            "truckstop_id": int(station["OPIS Truckstop ID"]),
            "name": str(station["Truckstop Name"]),
            "address": str(station["Address"]),
            "city": str(station["City"]),
            "state": str(station["State"]),
            "latitude": float(station["Latitude"]),
            "longitude": float(station["Longitude"]),
            "retail_price": float(station["Retail Price"]),
            "distance_from_route_miles": round(
                float(station["Distance From Route Miles"]), 2
            ),
            "route_progress_miles": round(
                float(station["Route Progress Miles"]), 2
            ),
            "leg_distance_from_previous_miles": round(
                leg_distance, 2
            ),
            "leg_fuel_gallons": round(leg_distance / mpg, 2),
            "estimated_leg_cost": round(
                (leg_distance / mpg) * leg_price, 2
            ),
        })

        previous_node = node

    return {
        "route_distance_miles": round(route_distance, 2),
        "estimated_fuel_gallons": round(total_gallons, 2),
        "estimated_fuel_cost": round(best_cost[destination_index], 2),
        "estimated_cost_basis": (
            "Estimated from route-leg fuel consumption and CSV station "
            "prices. The first leg uses the first stop's listed price; "
            "subsequent legs use the price at the previous stop. "
            "Actual purchase costs may differ."
        ),
        "refueling_required": bool(selected_stops),
        "stops": selected_stops,
        "message": (
            f"Selected {len(selected_stops)} fuel stop(s)."
            if selected_stops
            else "No en-route fuel stops are required."
        ),
    }
