
"""Load, validate, and query the fuel-price assessment dataset."""

from pathlib import Path

import numpy as np
import pandas as pd


# Use the CSV containing the added city coordinates.
DATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "fuel-prices-with-coordinates.csv"
)

REQUIRED_COLUMNS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
    "Latitude",
    "Longitude",
]

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE",
    "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def load_fuel_prices(only_us=True):
    """Load and validate fuel prices, retaining coordinate columns."""

    if not DATA_FILE.is_file():
        raise FileNotFoundError(
            f"Fuel-price dataset not found at: {DATA_FILE}"
        )

    df = pd.read_csv(DATA_FILE)

    missing_columns = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing_columns:
        raise ValueError(
            "The fuel-price CSV is missing required columns: "
            f"{sorted(missing_columns)}"
        )

    if df.empty:
        raise ValueError("The fuel-price CSV contains no records.")

    # Keep the original station records, including repeated rows.
    df = df[REQUIRED_COLUMNS].copy()

    text_columns = [
        "Truckstop Name",
        "Address",
        "City",
        "State",
    ]

    for column in text_columns:
        df[column] = df[column].astype("string").str.strip()

        if df[column].isna().any() or df[column].eq("").any():
            raise ValueError(
                f"The fuel-price CSV contains missing values in "
                f"'{column}'."
            )

    df["State"] = df["State"].str.upper()

    # Validate identifiers and fuel prices.
    for column in ["OPIS Truckstop ID", "Rack ID", "Retail Price"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

        if not np.isfinite(df[column].to_numpy(dtype=float)).all():
            raise ValueError(
                f"The fuel-price CSV contains invalid values in "
                f"'{column}'."
            )

    for column in ["OPIS Truckstop ID", "Rack ID"]:
        if (df[column] % 1 != 0).any():
            raise ValueError(
                f"Values in '{column}' must be whole numbers."
            )

        df[column] = df[column].astype("int64")

    if (df["Retail Price"] <= 0).any():
        raise ValueError("Retail Price must be greater than zero.")

    # Missing coordinates are allowed in the dataset.
    # They simply cannot be used for geographic station selection.
    for column in ["Latitude", "Longitude"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    valid_lat = df["Latitude"].between(-90, 90)
    valid_lon = df["Longitude"].between(-180, 180)

    df.loc[~valid_lat, "Latitude"] = np.nan
    df.loc[~valid_lon, "Longitude"] = np.nan

    if only_us:
        df = df[df["State"].isin(US_STATES)].copy()

    return df.reset_index(drop=True)


def get_fuel_stations_by_state(state, fuel_prices=None):
    """Return stations in a specified US state, sorted by price."""

    state = state.strip().upper()

    if state not in US_STATES:
        raise ValueError(f"'{state}' is not a recognized US state code.")

    if fuel_prices is None:
        fuel_prices = load_fuel_prices()

    return (
        fuel_prices[fuel_prices["State"] == state]
        .sort_values("Retail Price")
        .reset_index(drop=True)
    )


def _add_distance_from_location(df, latitude, longitude):
    """Add straight-line distance in miles from a given coordinate."""

    earth_radius_miles = 3958.7613

    lat1 = np.radians(latitude)
    lon1 = np.radians(longitude)
    lat2 = np.radians(df["Latitude"].to_numpy(dtype=float))
    lon2 = np.radians(df["Longitude"].to_numpy(dtype=float))

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    haversine = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(lat1)
        * np.cos(lat2)
        * np.sin(delta_lon / 2) ** 2
    )

    haversine = np.clip(haversine, 0, 1)

    df = df.copy()
    df["Distance Miles"] = (
        2
        * earth_radius_miles
        * np.arcsin(np.sqrt(haversine))
    )

    return df


def get_cheapest_stations(
    limit=10,
    fuel_prices=None,
    *,
    latitude=None,
    longitude=None,
    radius_miles=25,
):
    """
    Return the cheapest stations, optionally near a geographic location.

    Args:
        limit: Maximum number of stations to return.
        fuel_prices: Optional previously loaded DataFrame.
        latitude: Latitude of the location to search near.
        longitude: Longitude of the location to search near.
        radius_miles: Maximum straight-line distance from that location.

    Returns:
        DataFrame sorted by fuel price. When coordinates are provided,
        results also include 'Distance Miles'.
    """

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer.")

    if (latitude is None) != (longitude is None):
        raise ValueError(
            "Provide both latitude and longitude, or neither."
        )

    if (
        not isinstance(radius_miles, (int, float))
        or isinstance(radius_miles, bool)
        or not np.isfinite(radius_miles)
        or radius_miles < 0
    ):
        raise ValueError("radius_miles must be a finite non-negative number.")

    if latitude is not None:
        if (
            not np.isfinite(latitude)
            or not np.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise ValueError("Invalid latitude or longitude.")

    if fuel_prices is None:
        fuel_prices = load_fuel_prices()

    stations = fuel_prices.copy()

    # A location-specific search requires valid station coordinates.
    if latitude is not None:
        stations = stations.dropna(
            subset=["Latitude", "Longitude"]
        ).copy()

        stations = _add_distance_from_location(
            stations, latitude, longitude
        )

        stations = stations[
            stations["Distance Miles"] <= radius_miles
        ].copy()

        sort_columns = ["Retail Price", "Distance Miles"]
    else:
        # Without a location, preserve the original nationwide search.
        sort_columns = ["Retail Price", "State", "City"]

    return (
        stations.sort_values(sort_columns)
        .head(limit)
        .reset_index(drop=True)
    )
