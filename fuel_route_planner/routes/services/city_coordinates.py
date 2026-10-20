
import csv
import time
from pathlib import Path

import requests


# Existing input file and new output file
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

INPUT_FILE = DATA_DIR / "fuel-prices-for-be-assessment.csv"
OUTPUT_FILE = DATA_DIR / "fuel-prices-with-coordinates.csv"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

HEADERS = {
    "User-Agent": "FuelRoutePlannerAssessment/1.0 (city coordinate lookup)"
}


def get_city_coordinates(session, city, state):
    """Get approximate coordinates for a city in the United States."""
    params = {
        "city": city.strip(),
        "state": state.strip(),
        "country": "United States",
        "format": "jsonv2",
        "limit": 1,
    }

    response = session.get(
        NOMINATIM_URL,
        params=params,
        timeout=20,
    )
    response.raise_for_status()

    results = response.json()

    if not results:
        print(f"Coordinates not found: {city}, {state}")
        return "", ""

    return float(results[0]["lat"]), float(results[0]["lon"])


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input CSV not found: {INPUT_FILE}")

    with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)

        if not reader.fieldnames:
            raise ValueError("The input CSV has no column headers.")

        # Preserve all original columns and append coordinates.
        fieldnames = list(reader.fieldnames)

        for column in ("Latitude", "Longitude"):
            if column not in fieldnames:
                fieldnames.append(column)

        rows = list(reader)

    # Cache coordinates for repeated cities within this run.
    coordinate_cache = {}
    total = len(rows)

    with requests.Session() as session:
        session.headers.update(HEADERS)

        for index, row in enumerate(rows, start=1):
            city = (row.get("City") or "").strip()
            state = (row.get("State") or "").strip()
            key = (city.casefold(), state.casefold())

            if not city or not state:
                row["Latitude"] = ""
                row["Longitude"] = ""
                print(f"[{index}/{total}] Missing city/state")
                continue

            if key not in coordinate_cache:
                try:
                    latitude, longitude = get_city_coordinates(
                        session, city, state
                    )
                    coordinate_cache[key] = (latitude, longitude)

                except requests.RequestException as error:
                    print(f"[{index}/{total}] Lookup failed for "
                          f"{city}, {state}: {error}")
                    coordinate_cache[key] = ("", "")

                # Respect Nominatim's public-service rate limit.
                time.sleep(1.1)

            latitude, longitude = coordinate_cache[key]
            row["Latitude"] = latitude
            row["Longitude"] = longitude

            print(f"[{index}/{total}] {city}, {state}: "
                  f"{latitude}, {longitude}")

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nCompleted. Output saved to:\n{OUTPUT_FILE}")
    print(f"Processed {total} fuel station rows.")
    print(f"Unique cities looked up: {len(coordinate_cache)}")


if __name__ == "__main__":
    main()
