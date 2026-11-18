import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from pellet_stats import db, server, stats, weather


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpenWeather:
    """Stands in for urlopen. Day temperature = day of month, so results are easy to check."""

    def __init__(self, status=200):
        self.calls = []
        self.status = status

    def __call__(self, url, timeout=None):
        self.calls.append(url)
        if self.status != 200:
            raise HTTPError(url, self.status, "error", {}, None)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        assert q["appid"] == "KEY"
        if u.path.endswith("/geo/1.0/direct"):
            return FakeResponse(json.dumps([{"name": "Sofia", "country": "BG", "lat": 42.6977, "lon": 23.3219}]).encode())
        assert q["units"] == "metric"
        t = float(q["date"][-2:])
        body = {"temperature": {"min": t - 4, "max": t + 6, "morning": t - 2, "afternoon": t + 4,
                                "evening": t + 1, "night": t - 3}}
        return FakeResponse(json.dumps(body).encode())


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.place = db.create_place(self.conn, {"name": "House", "heating_type": "radiators", "area_m2": 120})
        self.a1 = db.create_pellet(self.conn, {"brand": "Acme", "bag_weight_kg": 15, "price_per_bag": 6})
        self.a2 = db.create_pellet(self.conn, {"brand": "Bolt", "bag_weight_kg": 10, "price_per_bag": 5})

    def add(self, fn, **data):
        return fn(self.conn, {"place_id": self.place["id"], **data})

    def test_delivery_by_bags_snapshots_kg_and_cost(self):
        d = self.add(db.create_delivery, pellet_id=self.a1["id"], date="2025-10-01", bags=65)
        self.assertEqual((d["kg"], d["cost"], d["bags"], d["brand"]), (975, 390, 65, "Acme"))
        db.update_pellet(self.conn, self.a1["id"], {"price_per_bag": 7})
        self.assertEqual(db.get_delivery(self.conn, d["id"])["cost"], 390)

    def test_stock_is_delivered_minus_burned_per_product(self):
        self.add(db.create_entry, pellet_id=self.a1["id"], date="2025-09-01", bags=10)  # before first delivery
        self.add(db.create_delivery, pellet_id=self.a1["id"], date="2025-10-01", bags=60)
        self.add(db.create_delivery, pellet_id=self.a2["id"], date="2025-11-01", bags=20)
        self.add(db.create_entry, pellet_id=self.a1["id"], date="2025-10-05", bags=12)
        self.add(db.create_entry, pellet_id=self.a2["id"], date="2025-11-05", bags=5)
        self.add(db.create_entry, date="2025-11-06", kg=15)  # pellet not specified
        s = db.stock(self.conn, self.place["id"])
        self.assertEqual(s["since"], "2025-10-01")
        self.assertEqual(s["delivered_kg"], 900 + 200)
        self.assertEqual(s["burned_kg"], 180 + 50 + 15)
        self.assertEqual(s["kg"], 1100 - 245)
        by = {p["brand"]: p for p in s["products"]}
        self.assertEqual(by["Acme"]["bags"], 48)
        self.assertEqual(by["Bolt"]["bags"], 15)
        self.assertEqual(by["Unspecified"]["kg"], -15)

    def test_no_deliveries_means_no_stock(self):
        self.add(db.create_entry, kg=10)
        self.assertEqual(db.stock(self.conn, self.place["id"])["since"], None)

    def test_delivery_validation(self):
        with self.assertRaises(db.ValidationError):
            self.add(db.create_delivery, bags=3)  # bags need a pellet product
        with self.assertRaises(db.ValidationError):
            self.add(db.create_delivery, kg=0)

    def test_deleting_place_removes_deliveries(self):
        self.add(db.create_delivery, kg=100)
        db.delete_place(self.conn, self.place["id"])
        self.assertEqual(db.list_deliveries(self.conn), [])

    def test_old_database_gets_new_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.db")
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE places (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                        "heating_type TEXT NOT NULL, area_m2 REAL NOT NULL, ceiling_height_m REAL, window_type TEXT, "
                        "insulation_type TEXT, building_year INTEGER, climate_zone TEXT, target_temp_c REAL, "
                        "burner_power_kw REAL, occupants INTEGER, notes TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
            old.execute("INSERT INTO places (name, heating_type, area_m2) VALUES ('Old', 'floor', 50)")
            old.commit()
            old.close()
            conn = db.connect(path)
            p = db.update_place(conn, 1, {"latitude": "-33.9", "longitude": "18.42"})
            self.assertEqual((p["latitude"], p["longitude"]), (-33.9, 18.42))
            conn.close()

    def test_coordinates_range(self):
        with self.assertRaises(db.ValidationError):
            db.update_place(self.conn, self.place["id"], {"latitude": 91})
        with self.assertRaises(db.ValidationError):
            db.update_place(self.conn, self.place["id"], {"longitude": -181})


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.fake = FakeOpenWeather()
        self.client = weather.OpenWeather("KEY", opener=self.fake)

    def test_daily_mean_prefers_four_readings(self):
        self.assertEqual(weather.daily_mean({"morning": 0, "afternoon": 8, "evening": 4, "night": -2, "min": -3, "max": 9}), 2.5)
        self.assertEqual(weather.daily_mean({"min": -3, "max": 9}), 3)
        self.assertIsNone(weather.daily_mean({}))

    def test_fetch_caches_and_skips_today_and_future(self):
        today = date(2025, 12, 5)
        r = weather.fetch_missing(self.conn, self.client, 42.69771, 23.32191, "2025-12-01", "2025-12-31", today=today)
        self.assertEqual(r, {"fetched": 4, "remaining": 0})
        temps = db.get_temperatures(self.conn, 42.69771, 23.32191, "2025-12-01", "2025-12-31")
        self.assertEqual(sorted(temps), ["2025-12-01", "2025-12-02", "2025-12-03", "2025-12-04"])
        self.assertEqual(temps["2025-12-02"]["temp_mean"], 2)  # (0 + 6 + 3 - 1) / 4
        # Cached, so a second run makes no calls. Nearby coordinates share the cache.
        r = weather.fetch_missing(self.conn, self.client, 42.6977, 23.3219, "2025-12-01", "2025-12-04", today=today)
        self.assertEqual((r["fetched"], len(self.fake.calls)), (0, 4))

    def test_fetch_in_batches(self):
        r = weather.fetch_missing(self.conn, self.client, 1, 2, "2025-01-01", "2025-01-31", limit=10, today=date(2026, 1, 1))
        self.assertEqual(r, {"fetched": 10, "remaining": 21})

    def test_bad_key_message(self):
        client = weather.OpenWeather("KEY", opener=FakeOpenWeather(status=401))
        with self.assertRaisesRegex(weather.WeatherError, "One Call API 3.0"):
            client.day_summary(1, 2, "2025-01-01")

    def test_geocode(self):
        self.assertEqual(self.client.geocode("Sofia")[0]["lat"], 42.6977)

    def test_find_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("# comment\nOPENWEATHER_API_KEY='abc123'\n")
            self.assertEqual(weather.find_api_key(None, env={}, dotenv=env_file), "abc123")
            self.assertEqual(weather.find_api_key(None, env={"OPENWEATHER_API_KEY": "env"}, dotenv=env_file), "env")
            self.assertEqual(weather.find_api_key("cli", env={"OPENWEATHER_API_KEY": "env"}), "cli")
            self.assertIsNone(weather.find_api_key(None, env={}, dotenv=Path(tmp) / "none"))


class TemperatureStatsTests(unittest.TestCase):
    def test_period_summary(self):
        temps = {
            "2025-12-01": {"temp_mean": 0.0, "temp_min": -5.0, "temp_max": 4.0},
            "2025-12-02": {"temp_mean": 4.0, "temp_min": 1.0, "temp_max": 9.0},
            "2025-12-03": {"temp_mean": 17.0, "temp_min": 12.0, "temp_max": 22.0},
        }
        entries = [{"date": "2025-12-01", "kg": 20}, {"date": "2025-12-02", "kg": 16}, {"date": "2025-12-09", "kg": 99}]
        s = stats.temperature_summary(temps, entries, "2025-12-01", "2025-12-03")
        self.assertEqual(s["temp_mean"], 7.0)
        self.assertEqual((s["temp_min"], s["temp_max"]), (-5.0, 22.0))
        self.assertEqual(s["hdd"], 18 + 14)  # the 17 °C day is above the 15 °C threshold
        self.assertEqual(s["kg"], 36)
        self.assertEqual(s["kg_per_hdd"], round(36 / 32, 3))
        self.assertEqual(s["days_with_temp"], 3)

    def test_incomplete_period_has_no_kg_per_hdd(self):
        s = stats.temperature_summary({"2025-12-01": {"temp_mean": 0.0}}, [], "2025-12-01", "2025-12-02")
        self.assertEqual((s["temp_mean"], s["days_with_temp"], s["kg_per_hdd"]), (0.0, 1, None))

    def test_monthly_temperatures(self):
        place = {"area_m2": 100}
        entries = [{"date": "2025-12-01", "kg": 10, "cost": None}, {"date": "2025-12-02", "kg": 10, "cost": None}]
        temps = {"2025-12-01": {"temp_mean": 2.0}, "2025-12-02": {"temp_mean": 4.0}}
        month = stats.place_stats(place, entries, temps=temps)["monthly"][0]
        self.assertEqual((month["temp_mean"], month["hdd"], month["kg_per_hdd"]), (3.0, 30, round(20 / 30, 3)))
        self.assertNotIn("temp_mean", stats.place_stats(place, entries)["monthly"][0])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.fake = FakeOpenWeather()
        self.app = server.make_app(self.conn, weather.OpenWeather("KEY", opener=self.fake))
        self.pid = self.call("POST", "/api/places", {"name": "A", "heating_type": "floor", "area_m2": 100})[1]["id"]

    def call(self, method, path, body=None):
        url = urlparse(path)
        status, _, payload = self.app(method, url.path, url.query, body or {})
        return status, payload

    def test_storage_flow(self):
        status, d = self.call("POST", "/api/deliveries", {"place_id": self.pid, "date": "2025-10-01", "kg": 500})
        self.assertEqual(status, 201)
        self.call("POST", "/api/entries", {"place_id": self.pid, "date": "2025-10-02", "kg": 40})
        self.assertEqual(self.call("GET", f"/api/places/{self.pid}/stock")[1]["kg"], 460)
        self.assertEqual(self.call("GET", "/api/stock")[1][0]["kg"], 460)
        self.call("PUT", f"/api/deliveries/{d['id']}", {"date": "2025-10-01", "kg": 600})
        self.assertEqual(self.call("GET", f"/api/places/{self.pid}/stock")[1]["kg"], 560)
        self.assertEqual(len(self.call("GET", f"/api/deliveries?place_id={self.pid}")[1]), 1)
        self.assertEqual(self.call("DELETE", f"/api/deliveries/{d['id']}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/deliveries/{d['id']}")[0], 404)

    def test_weather_flow(self):
        self.assertTrue(self.call("GET", "/api/options")[1]["weather_enabled"])
        q = "from=2025-12-01&to=2025-12-03"
        self.assertEqual(self.call("POST", f"/api/places/{self.pid}/weather/fetch?{q}")[0], 400)  # no location yet
        self.call("PUT", f"/api/places/{self.pid}", {"latitude": 42.7, "longitude": 23.3})
        self.call("POST", "/api/entries", {"place_id": self.pid, "date": "2025-12-02", "kg": 30})
        status, r = self.call("GET", f"/api/places/{self.pid}/weather?{q}")
        self.assertEqual((status, r["missing"], r["temp_mean"]), (200, 3, None))
        status, r = self.call("POST", f"/api/places/{self.pid}/weather/fetch?{q}")
        self.assertEqual((status, r["fetched"], r["missing"], r["days_with_temp"]), (200, 3, 0, 3))
        self.assertEqual(r["temp_mean"], 2.0)  # day means are 1, 2 and 3 °C
        self.assertEqual(r["kg"], 30)
        month = self.call("GET", f"/api/places/{self.pid}/stats")[1]["monthly"][0]
        self.assertEqual(month["temp_mean"], 2.0)
        self.assertEqual(self.call("GET", "/api/geocode?q=Sofia")[1][0]["country"], "BG")

    def test_weather_errors(self):
        self.assertEqual(self.call("GET", f"/api/places/{self.pid}/weather?from=2025-12-05&to=2025-12-01")[0], 400)
        self.assertEqual(self.call("GET", f"/api/places/{self.pid}/weather?from=bad&to=2025-12-01")[0], 400)
        self.call("PUT", f"/api/places/{self.pid}", {"latitude": 42.7, "longitude": 23.3})
        app = server.make_app(self.conn, weather.OpenWeather("KEY", opener=FakeOpenWeather(status=401)))
        status, _, payload = app("POST", f"/api/places/{self.pid}/weather/fetch", "from=2025-12-01&to=2025-12-01", {})
        self.assertEqual(status, 502)
        self.assertIn("One Call", payload["error"])

    def test_weather_off_without_key(self):
        app = server.make_app(self.conn)
        self.assertFalse(app("GET", "/api/options", "", {})[2]["weather_enabled"])
        self.assertEqual(app("GET", "/api/geocode", "q=Sofia", {})[0], 400)


if __name__ == "__main__":
    unittest.main()
