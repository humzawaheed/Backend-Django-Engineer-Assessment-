"""Select affordable fuel stops along a driving route."""

import math

import numpy as np
import pandas as pd


EARTH_RADIUS_MILES = 3958.7613
MIN_SAVINGS_PER_EXTRA_STOP_USD = 10.0



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
    """Plan fuel stops with a full starting tank and explicit fuel purchases."""

    if not math.isfinite(mpg) or mpg <= 0:
        raise ValueError("mpg must be a finite positive number.")

    if not math.isfinite(range_miles) or range_miles <= 0:
        raise ValueError("range_miles must be a finite positive number.")

    if (
        not math.isfinite(safety_margin_miles)
        or not 0 <= safety_margin_miles < range_miles
    ):
        raise ValueError(
            "Safety margin must be non-negative and less than range."
        )

    if not math.isfinite(corridor_miles) or corridor_miles < 0:
        raise ValueError("corridor_miles must be non-negative.")

    try:
        route_distance = float(route["distance_miles"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Route must include a valid distance_miles value.")

    if not math.isfinite(route_distance) or route_distance <= 0:
        raise ValueError("Route distance must be a finite positive number.")

    if fuel_prices.empty:
        raise ValueError("No fuel-price records are available.")

    required_columns = {
        "OPIS Truckstop ID",
        "Truckstop Name",
        "Address",
        "City",
        "State",
        "Retail Price",
        "Latitude",
        "Longitude",
    }
    missing = required_columns - set(fuel_prices.columns)
    if missing:
        raise ValueError(
            f"Fuel-price data is missing columns: {sorted(missing)}"
        )

    prices = pd.to_numeric(fuel_prices["Retail Price"], errors="coerce")
    prices = prices[np.isfinite(prices) & (prices > 0)]

    if prices.empty:
        raise ValueError("No valid positive fuel prices are available.")

    usable_range_miles = range_miles - safety_margin_miles
    tank_capacity_gallons = usable_range_miles / mpg
    average_price = float(prices.mean())

    candidates = _find_route_candidates(
        route,
        fuel_prices,
        corridor_miles=corridor_miles,
    )

    base_result = {
        "route_distance_miles": round(route_distance, 2),
        "estimated_fuel_gallons": round(route_distance / mpg, 2),
        "estimated_fuel_cost": round(
            (route_distance / mpg) * average_price, 2
        ),
        "estimated_cost_basis": (
            "Estimated total trip fuel-consumption cost using the mean "
            "listed dataset price. Assumes a full tank at departure; "
            "en-route purchases are reported separately."
        ),
        "refueling_required": route_distance > usable_range_miles,
        "stops": [],
        "legs": [],
        "estimated_en_route_purchase_cost": 0.0,
        "message": "",
    }

    if route_distance <= usable_range_miles:
        base_result["refueling_required"] = False
        base_result["message"] = (
            "The destination is within the usable range of the assumed "
            "full starting tank."
        )
        return base_result

    if candidates.empty:
        base_result["estimated_fuel_cost"] = None
        base_result["estimated_en_route_purchase_cost"] = None
        base_result["estimated_cost_basis"] = (
            "No feasible estimate: no candidate fuel stations were found "
            "within the configured route corridor."
        )
        base_result["message"] = (
            "No suitable fuel stations were found near the route. "
            "Try widening the corridor or checking station coordinates."
        )
        return base_result

    nodes = [
        {"kind": "start", "progress": 0.0, "off_route": 0.0}
    ]

    for station in candidates.to_dict("records"):
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
        index for index, node in enumerate(nodes)
        if node["kind"] == "start"
    )
    destination_index = next(
        index for index, node in enumerate(nodes)
        if node["kind"] == "destination"
    )

    def distance_between(first, second):
        return (
            second["progress"] - first["progress"]
            + first["off_route"]
            + second["off_route"]
        )

    # The assumed starting tank is full. Reach the furthest station that
    # can be reached before using the safety reserve.
    start_node = nodes[start_index]
    reachable_from_start = [
        index
        for index in range(start_index + 1, destination_index)
        if nodes[index]["kind"] == "station"
        and 0 < distance_between(start_node, nodes[index])
        <= usable_range_miles
    ]

    if not reachable_from_start:
        base_result["estimated_fuel_cost"] = None
        base_result["estimated_en_route_purchase_cost"] = None
        base_result["estimated_cost_basis"] = (
            "No feasible plan: no fuel station is reachable from the "
            "starting location within the usable tank range."
        )
        base_result["message"] = (
            "No fuel station can be reached before the safety reserve. "
            "Try widening the corridor or checking station coordinates."
        )
        return base_result

    current_index = max(
        reachable_from_start,
        key=lambda index: nodes[index]["progress"],
    )
    current_node = nodes[current_index]
    fuel_remaining_miles = (
        usable_range_miles
        - distance_between(start_node, current_node)
    )

    legs = [{
        "from": "start",
        "to": str(current_node["station"]["Truckstop Name"]),
        "distance_miles": round(
            distance_between(start_node, current_node), 2
        ),
        "fuel_gallons": round(
            distance_between(start_node, current_node) / mpg, 2
        ),
        "fuel_source": "assumed_starting_tank",
        "estimated_purchase_cost": 0.0,
    }]
    stops = []
    total_purchase_cost = 0.0
    visited_indexes = {current_index}

    while current_index != destination_index:
        current_node = nodes[current_index]
        destination_node = nodes[destination_index]
        distance_to_destination = distance_between(
            current_node, destination_node
        )

        if distance_to_destination <= fuel_remaining_miles:
            legs.append({
                "from": str(current_node["station"]["Truckstop Name"]),
                "to": "destination",
                "distance_miles": round(distance_to_destination, 2),
                "fuel_gallons": round(distance_to_destination / mpg, 2),
                "fuel_source": "fuel_remaining_in_tank",
                "estimated_purchase_cost": 0.0,
            })
            current_index = destination_index
            break

        current_station = current_node["station"]
        current_price = float(current_station["Retail Price"])

        reachable_stations = [
            index
            for index in range(current_index + 1, destination_index)
            if nodes[index]["kind"] == "station"
            and index not in visited_indexes
            and 0 < distance_between(current_node, nodes[index])
            <= usable_range_miles
        ]

        cheaper_stations = []

        for index in reachable_stations:
            candidate_price = float(
                nodes[index]["station"]["Retail Price"]
            )
            if candidate_price >= current_price:
                continue

            distance_to_candidate = distance_between(
                current_node, nodes[index]
            )
            distance_after_candidate = max(
                0.0,
                distance_to_destination - distance_to_candidate,
            )

            # Estimate the savings over at most one usable tank range.
            gallons_compared = (
                min(distance_after_candidate, usable_range_miles) / mpg
            )
            estimated_savings = (
                gallons_compared * (current_price - candidate_price)
            )

            if estimated_savings > MIN_SAVINGS_PER_EXTRA_STOP_USD:
                cheaper_stations.append(index)

        if cheaper_stations:
            # Buy only enough to reach the nearest cheaper station.
            target_index = min(
                cheaper_stations,
                key=lambda index: distance_between(
                    current_node, nodes[index]
                ),
            )
            target_node = nodes[target_index]
            target_distance = distance_between(current_node, target_node)
            purchase_gallons = max(
                0.0,
                (target_distance - fuel_remaining_miles) / mpg,
            )
        else:
            if distance_to_destination <= usable_range_miles:
                target_index = destination_index
                target_node = destination_node
                target_distance = distance_to_destination
                purchase_gallons = max(
                    0.0,
                    (target_distance - fuel_remaining_miles) / mpg,
                )
            else:
                if not reachable_stations:
                    base_result["estimated_fuel_cost"] = None
                    base_result["estimated_en_route_purchase_cost"] = None
                    base_result["estimated_cost_basis"] = (
                        "No feasible plan: no station is reachable from "
                        "the current stop within the usable tank range."
                    )
                    base_result["message"] = (
                        "A safe fuel-stop plan could not be found. "
                        "Try widening the corridor or reviewing station "
                        "coverage."
                    )
                    return base_result

                # No cheaper station is reachable after filling. Fill the
                # tank, then head to the cheapest reachable station.
                target_index = min(
                    reachable_stations,
                    key=lambda index: (
                        float(nodes[index]["station"]["Retail Price"]),
                        -nodes[index]["progress"],
                    ),
                )
                target_node = nodes[target_index]
                target_distance = distance_between(
                    current_node, target_node
                )
                purchase_gallons = max(
                    0.0,
                    tank_capacity_gallons
                    - fuel_remaining_miles / mpg,
                )

        if purchase_gallons > tank_capacity_gallons:
            base_result["estimated_fuel_cost"] = None
            base_result["estimated_en_route_purchase_cost"] = None
            base_result["message"] = (
                "A safe fuel-stop plan could not be found with the "
                "configured tank range."
            )
            return base_result

        purchase_cost = purchase_gallons * current_price
        fuel_remaining_miles += purchase_gallons * mpg
        fuel_remaining_miles = min(
            fuel_remaining_miles,
            usable_range_miles,
        )

        if purchase_gallons > 0:
            total_purchase_cost += purchase_cost
            stops.append({
                "truckstop_id": int(current_station["OPIS Truckstop ID"]),
                "name": str(current_station["Truckstop Name"]),
                "address": str(current_station["Address"]),
                "city": str(current_station["City"]),
                "state": str(current_station["State"]),
                "latitude": float(current_station["Latitude"]),
                "longitude": float(current_station["Longitude"]),
                "retail_price": current_price,
                "distance_from_route_miles": round(
                    float(current_node["off_route"]), 2
                ),
                "route_progress_miles": round(
                    float(current_node["progress"]), 2
                ),
                "fuel_purchased_gallons": round(purchase_gallons, 2),
                "estimated_purchase_cost": round(purchase_cost, 2),
                "estimated_leg_cost": round(purchase_cost, 2),
            })

        fuel_remaining_miles -= target_distance
        legs.append({
            "from": str(current_station["Truckstop Name"]),
            "to": (
                "destination"
                if target_node["kind"] == "destination"
                else str(target_node["station"]["Truckstop Name"])
            ),
            "distance_miles": round(target_distance, 2),
            "fuel_gallons": round(target_distance / mpg, 2),
            "fuel_source": (
                "fuel_purchased_at_previous_stop"
                if purchase_gallons > 0
                else "fuel_remaining_in_tank"
            ),
            "estimated_purchase_cost": round(purchase_cost, 2),
        })

        if target_index == destination_index:
            current_index = destination_index
            break

        if fuel_remaining_miles < -1e-9:
            base_result["estimated_fuel_cost"] = None
            base_result["estimated_en_route_purchase_cost"] = None
            base_result["message"] = (
                "A safe fuel-stop plan could not be found with the "
                "configured tank range."
            )
            return base_result

        current_index = target_index
        visited_indexes.add(current_index)

    base_result["stops"] = stops
    base_result["legs"] = legs
    base_result["refueling_required"] = bool(stops)
    base_result["estimated_en_route_purchase_cost"] = round(
        total_purchase_cost, 2
    )
    base_result["message"] = (
        f"Selected {len(stops)} fuel stop(s). "
        f"Usable range includes a {safety_margin_miles:g}-mile "
        "safety reserve."
    )
    return base_result


