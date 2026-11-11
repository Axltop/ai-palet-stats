"""HTTP server: a small JSON API plus the static single page app. Standard library only."""

import argparse
import csv
import io
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from . import db, stats

STATIC_DIR = Path(__file__).parent / "static"


class NotFound(Exception):
    pass


def make_app(conn):
    """Return a function (method, path, query, body) -> (status, content_type, payload)."""
    lock = Lock()

    def entries_for(place_id):
        return db.list_entries(conn, place_id=place_id)

    def found(value):
        if value is None or value is False:
            raise NotFound()
        return value

    routes = []

    def route(method, pattern):
        def wrap(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn))
            return fn
        return wrap

    @route("GET", r"/api/options")
    def options(q, body):
        return {
            "heating_types": db.HEATING_TYPES,
            "window_types": db.WINDOW_TYPES,
            "insulation_types": db.INSULATION_TYPES,
            "climate_zones": db.CLIMATE_ZONES,
            "pellet_grades": db.PELLET_GRADES,
        }

    @route("GET", r"/api/places")
    def places_list(q, body):
        return db.list_places(conn)

    @route("POST", r"/api/places")
    def places_create(q, body):
        return 201, db.create_place(conn, body)

    @route("GET", r"/api/places/(\d+)")
    def places_get(q, body, pid):
        return found(db.get_place(conn, int(pid)))

    @route("PUT", r"/api/places/(\d+)")
    def places_update(q, body, pid):
        return found(db.update_place(conn, int(pid), body))

    @route("DELETE", r"/api/places/(\d+)")
    def places_delete(q, body, pid):
        found(db.delete_place(conn, int(pid)))
        return {"deleted": True}

    @route("GET", r"/api/places/(\d+)/stats")
    def places_stats(q, body, pid):
        place = found(db.get_place(conn, int(pid)))
        return stats.place_stats(place, entries_for(place["id"]), q.get("season"))

    @route("GET", r"/api/compare")
    def compare(q, body):
        places = db.list_places(conn)
        pairs = [(p, entries_for(p["id"])) for p in places]
        seasons = sorted({stats.season_of(e["date"]) for _, es in pairs for e in es})
        return {
            "season": q.get("season"),
            "available_seasons": seasons,
            "places": stats.compare_places(pairs, q.get("season")),
        }

    @route("GET", r"/api/pellets")
    def pellets_list(q, body):
        return db.list_pellets(conn)

    @route("POST", r"/api/pellets")
    def pellets_create(q, body):
        return 201, db.create_pellet(conn, body)

    @route("PUT", r"/api/pellets/(\d+)")
    def pellets_update(q, body, pid):
        return found(db.update_pellet(conn, int(pid), body))

    @route("DELETE", r"/api/pellets/(\d+)")
    def pellets_delete(q, body, pid):
        found(db.delete_pellet(conn, int(pid)))
        return {"deleted": True}

    @route("GET", r"/api/entries")
    def entries_list(q, body):
        return db.list_entries(conn, place_id=q.get("place_id"))

    @route("POST", r"/api/entries")
    def entries_create(q, body):
        return 201, db.create_entry(conn, body)

    @route("GET", r"/api/entries/(\d+)")
    def entries_get(q, body, eid):
        return found(db.get_entry(conn, int(eid)))

    @route("PUT", r"/api/entries/(\d+)")
    def entries_update(q, body, eid):
        return found(db.update_entry(conn, int(eid), body))

    @route("DELETE", r"/api/entries/(\d+)")
    def entries_delete(q, body, eid):
        found(db.delete_entry(conn, int(eid)))
        return {"deleted": True}

    @route("GET", r"/api/export\.csv")
    def export_csv(q, body):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["date", "place", "pellet", "bags", "kg", "cost", "notes"])
        for e in reversed(db.list_entries(conn, place_id=q.get("place_id"))):
            writer.writerow([e["date"], e["place_name"], e["brand"] or "", e["bags"] or "",
                             e["kg"], "" if e["cost"] is None else e["cost"], e["notes"] or ""])
        return 200, "text/csv; charset=utf-8", out.getvalue()

    def handle(method, path, query, body):
        q = {k: v[0] for k, v in parse_qs(query).items()}
        for m, pattern, fn in routes:
            match = pattern.match(path)
            if m == method and match:
                try:
                    with lock:
                        result = fn(q, body, *match.groups())
                except db.ValidationError as exc:
                    return 400, "application/json", {"error": str(exc)}
                except NotFound:
                    return 404, "application/json", {"error": "not found"}
                if isinstance(result, tuple) and len(result) == 3:
                    return result
                if isinstance(result, tuple):
                    return result[0], "application/json", result[1]
                return 200, "application/json", result
        return 404, "application/json", {"error": "no such endpoint"}

    return handle


class Handler(BaseHTTPRequestHandler):
    app = None
    quiet = False

    def log_message(self, fmt, *args):
        if not self.quiet:
            super().log_message(fmt, *args)

    def _send(self, status, ctype, payload):
        data = payload if isinstance(payload, bytes) else (
            payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            body = {}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, "application/json", {"error": "invalid JSON"})
                if not isinstance(body, dict):
                    return self._send(400, "application/json", {"error": "expected a JSON object"})
            return self._send(*self.app(method, url.path, url.query, body))
        if method != "GET":
            return self._send(405, "text/plain", "method not allowed")
        rel = url.path.lstrip("/") or "index.html"
        file = (STATIC_DIR / rel).resolve()
        if not file.is_file() or STATIC_DIR.resolve() not in file.parents:
            file = STATIC_DIR / "index.html"  # single page app fallback
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, ctype, file.read_bytes())

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pellet burner consumption statistics")
    parser.add_argument("--db", default="pellets.db", help="SQLite file (default: pellets.db)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="fill an empty database with sample data")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    if args.demo:
        from .demo import seed
        print("Demo data:", seed(conn))
    Handler.app = staticmethod(make_app(conn))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Pellet stats running at http://{args.host}:{args.port}  (database: {args.db})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
