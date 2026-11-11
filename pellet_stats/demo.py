"""Sample data so the app has something to show on first run (python -m pellet_stats --demo)."""

import random
from datetime import date, timedelta

from . import db

# Rough share of heating need per month in a central European climate.
MONTH_FACTOR = {9: 0.15, 10: 0.45, 11: 0.8, 12: 1.0, 1: 1.05, 2: 0.9, 3: 0.65, 4: 0.35, 5: 0.1}


def seed(conn):
    if db.list_places(conn):
        return "database already has places, demo data not added"
    rng = random.Random(42)
    house = db.create_place(conn, {
        "name": "Family house", "heating_type": "radiators", "area_m2": 140, "ceiling_height_m": 2.6,
        "window_type": "double", "insulation_type": "average", "building_year": 1998,
        "climate_zone": "temperate", "target_temp_c": 21.5, "burner_power_kw": 24, "occupants": 4,
    })
    cottage = db.create_place(conn, {
        "name": "Mountain cottage", "heating_type": "direct", "area_m2": 65, "ceiling_height_m": 2.4,
        "window_type": "single", "insulation_type": "poor", "building_year": 1975,
        "climate_zone": "cold", "target_temp_c": 19, "burner_power_kw": 9, "occupants": 2,
    })
    flat = db.create_place(conn, {
        "name": "New build", "heating_type": "floor", "area_m2": 110, "ceiling_height_m": 2.7,
        "window_type": "triple", "insulation_type": "good", "building_year": 2019,
        "climate_zone": "temperate", "target_temp_c": 22, "burner_power_kw": 15, "occupants": 3,
    })
    a1 = db.create_pellet(conn, {"brand": "ForestFire", "name": "Premium", "grade": "ENplus A1",
                                 "bag_weight_kg": 15, "price_per_bag": 5.40})
    a2 = db.create_pellet(conn, {"brand": "WoodPower", "name": "Eco", "grade": "ENplus A2",
                                 "bag_weight_kg": 15, "price_per_bag": 4.60})
    big = db.create_pellet(conn, {"brand": "ForestFire", "name": "Big bag", "grade": "ENplus A1",
                                  "bag_weight_kg": 25, "price_per_bag": 8.50})

    # kg per heating day at the coldest point, per place; cottage is used on weekends only.
    plans = [(house, 26, [a1, a2], 1.0), (flat, 11, [a1], 1.0), (cottage, 14, [a2, big], 0.3)]
    today = date.today()
    start = date(today.year - 2 if today.month < 9 else today.year - 1, 9, 15)
    count = 0
    for place, peak, products, usage in plans:
        d = start
        while d <= today:
            # Entries are refills: each one covers the days since the previous refill.
            step = rng.choice([1, 2, 3]) if place is not cottage else 1
            factor = MONTH_FACTOR.get(d.month, 0)
            if factor and rng.random() < usage:
                kg = peak * factor * step * rng.uniform(0.75, 1.25)
                if place is cottage:
                    kg *= 2  # weekend visits burn more per day
                product = rng.choice(products)
                bags = max(round(kg / product["bag_weight_kg"] * 2) / 2, 0.5)
                db.create_entry(conn, {"place_id": place["id"], "pellet_id": product["id"],
                                       "date": d.isoformat(), "bags": bags})
                count += 1
            d += timedelta(days=step)
    return f"added 3 places, 3 pellet products and {count} consumption entries"
