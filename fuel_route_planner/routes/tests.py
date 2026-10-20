import pandas as pd
from django.test import SimpleTestCase

from routes.services.fuel_calculator import calculate_fuel_plan


class CalculateFuelPlanTests(SimpleTestCase):
    def test_leg_costs_reconcile_with_en_route_purchase_cost(self):
        fuel_prices = pd.DataFrame([
            {
                "OPIS Truckstop ID": 1,
                "Truckstop Name": "Expensive station",
                "Address": "Route",
                "City": "Test City",
                "State": "TX",
                "Retail Price": 5.0,
                "Latitude": 0.0,
                "Longitude": 2.0,
            },
            {
                "OPIS Truckstop ID": 2,
                "Truckstop Name": "Cheap station",
                "Address": "Route",
                "City": "Test City",
                "State": "TX",
                "Retail Price": 2.0,
                "Latitude": 0.0,
                "Longitude": 4.0,
            },
        ])
        route = {
            "distance_miles": 600.0,
            "coordinates": [
                [0.0, 0.0],
                [2.0, 0.0],
                [4.0, 0.0],
                [6.0, 0.0],
            ],
        }

        plan = calculate_fuel_plan(route, fuel_prices)

        self.assertEqual(len(plan["stops"]), 1)
        self.assertEqual(plan["stops"][0]["name"], "Cheap station")
        self.assertEqual(
            plan["estimated_en_route_purchase_cost"],
            sum(
                leg["estimated_purchase_cost"]
                for leg in plan["legs"]
            ),
        )
        self.assertEqual(
            plan["stops"][0]["estimated_leg_cost"],
            plan["legs"][-1]["estimated_purchase_cost"],
        )
        self.assertEqual(
            plan["legs"][0]["estimated_purchase_cost"],
            0.0,
        )
