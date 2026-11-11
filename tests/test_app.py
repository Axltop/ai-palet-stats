import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from pellet_stats import db, demo, server, stats


class StatsTests(unittest.TestCase):
    place = {"id": 1, "name": "House", "area_m2": 100, "ceiling_height_m": 2.5}

    def test_seasons_run_july_to_june(self):
        self.assertEqual(stats.season_of("2025-06-30"), "2024/25")
        self.assertEqual(stats.season_of("2025-07-01"), "2025/26")
        self.assertEqual(stats.season_of("2026-01-15"), "2025/26")

    def test_summary_and_per_area(self):
        entries = [
            {"date": "2025-12-01", "kg": 30, "cost": 10.0, "brand": "A"},
            {"date": "2025-12-10", "kg": 30, "cost": 12.0, "brand": "B"},
        ]
        s = stats.place_stats(self.place, entries)["summary"]
        self.assertEqual(s["total_kg"], 60)
        self.assertEqual(s["total_cost"], 22)
        self.assertEqual(s["days"], 10)
        self.assertEqual(s["kg_per_day"], 6)
        self.assertEqual(s["kg_per_m2"], 0.6)
        self.assertEqual(s["kg_per_m3"], 0.24)
        self.assertEqual(s["cost_per_m2"], 0.22)

    def test_monthly_kg_per_day_uses_logged_days_only(self):
        entries = [{"date": "2025-11-21", "kg": 20, "cost": None}, {"date": "2025-11-30", "kg": 20, "cost": None}]
        month = stats.place_stats(self.place, entries)["monthly"][0]
        self.assertEqual(month["days"], 10)
        self.assertEqual(month["kg_per_day"], 4)

    def test_season_filter_and_breakdown(self):
        entries = [
            {"date": "2025-03-01", "kg": 10, "cost": 3},
            {"date": "2025-10-01", "kg": 20, "cost": 7},
            {"date": "2026-02-01", "kg": 30, "cost": 9},
        ]
        result = stats.place_stats(self.place, entries, "2025/26")
        self.assertEqual(result["summary"]["total_kg"], 50)
        self.assertEqual(result["available_seasons"], ["2024/25", "2025/26"])
        self.assertEqual([m["month"] for m in result["monthly"]], ["2025-10", "2026-02"])
        all_time = stats.place_stats(self.place, entries)
        self.assertEqual([(s["season"], s["kg"]) for s in all_time["seasons"]], [("2024/25", 10), ("2025/26", 50)])

    def test_no_entries(self):
        s = stats.place_stats(self.place, [])["summary"]
        self.assertEqual(s["total_kg"], 0)
        self.assertIsNone(s["kg_per_m2"])

    def test_cost_unknown_is_not_zero(self):
        s = stats.place_stats(self.place, [{"date": "2025-12-01", "kg": 10, "cost": None}])["summary"]
        self.assertIsNone(s["total_cost"])
        self.assertIsNone(s["price_per_kg"])


class DbTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.place = db.create_place(self.conn, {"name": "Flat", "heating_type": "floor", "area_m2": "80"})
        self.pellet = db.create_pellet(self.conn, {"brand": "Acme", "bag_weight_kg": 15, "price_per_bag": 6})

    def test_validation(self):
        with self.assertRaises(db.ValidationError):
            db.create_place(self.conn, {"name": "X", "heating_type": "lava", "area_m2": 50})
        with self.assertRaises(db.ValidationError):
            db.create_place(self.conn, {"name": "X", "heating_type": "floor", "area_m2": 0})
        with self.assertRaises(db.ValidationError):
            db.create_entry(self.conn, {"place_id": self.place["id"], "bags": 2})  # bags need a pellet

    def test_entry_by_bags_uses_pellet_weight_and_price(self):
        e = db.create_entry(self.conn, {"place_id": self.place["id"], "pellet_id": self.pellet["id"],
                                        "date": "2025-12-01", "bags": 2})
        self.assertEqual((e["kg"], e["cost"], e["brand"]), (30, 12, "Acme"))

    def test_price_change_keeps_history(self):
        e = db.create_entry(self.conn, {"place_id": self.place["id"], "pellet_id": self.pellet["id"], "bags": 1})
        db.update_pellet(self.conn, self.pellet["id"], {"price_per_bag": 9})
        self.assertEqual(db.get_entry(self.conn, e["id"])["cost"], 6)

    def test_entry_by_kg_with_cost_override(self):
        e = db.create_entry(self.conn, {"place_id": self.place["id"], "pellet_id": self.pellet["id"],
                                        "kg": 10, "cost": 5})
        self.assertEqual((e["kg"], e["cost"]), (10, 5))

    def test_delete_place_removes_entries(self):
        db.create_entry(self.conn, {"place_id": self.place["id"], "kg": 10})
        db.delete_place(self.conn, self.place["id"])
        self.assertEqual(db.list_entries(self.conn), [])

    def test_demo_seed(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        demo.seed(conn)
        self.assertEqual(len(db.list_places(conn)), 3)
        self.assertGreater(len(db.list_entries(conn)), 100)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = db.connect(":memory:")
        handler = type("H", (server.Handler,), {"app": staticmethod(server.make_app(conn)), "quiet": True})
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.read().decode()
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode()

    def test_full_flow(self):
        status, body = self.call("POST", "/api/places", {"name": "A", "heating_type": "radiators", "area_m2": 100})
        self.assertEqual(status, 201)
        pid = json.loads(body)["id"]
        status, body = self.call("POST", "/api/entries", {"place_id": pid, "date": "2025-12-01", "kg": 50})
        self.assertEqual(status, 201)
        status, body = self.call("GET", f"/api/places/{pid}/stats?season=2025/26")
        self.assertEqual(json.loads(body)["summary"]["kg_per_m2"], 0.5)
        status, body = self.call("GET", "/api/compare")
        self.assertEqual(json.loads(body)["places"][0]["total_kg"], 50)
        status, body = self.call("GET", "/api/export.csv")
        self.assertIn("2025-12-01,A,,,50.0", body)

    def test_errors(self):
        self.assertEqual(self.call("POST", "/api/places", {"name": "B"})[0], 400)
        self.assertEqual(self.call("GET", "/api/places/999")[0], 404)

    def test_serves_app(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Pellet Stats", body)


if __name__ == "__main__":
    unittest.main()
