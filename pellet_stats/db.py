"""SQLite storage. One file, no ORM."""

import sqlite3
from datetime import date

HEATING_TYPES = {
    "floor": "Floor heating",
    "radiators": "Radiators",
    "direct": "Direct pellet burner (stove)",
    "mixed": "Mixed (floor + radiators)",
}
WINDOW_TYPES = {
    "single": "Single glazing",
    "double": "Double glazing",
    "triple": "Triple glazing",
    "mixed": "Mixed",
}
INSULATION_TYPES = {
    "none": "None",
    "poor": "Poor (old, thin)",
    "average": "Average (5-10 cm)",
    "good": "Good (10-20 cm)",
    "excellent": "Excellent / passive house",
}
CLIMATE_ZONES = {
    "mild": "Mild",
    "temperate": "Temperate",
    "cold": "Cold",
    "very_cold": "Very cold / mountain",
}
PELLET_GRADES = ["ENplus A1", "ENplus A2", "DINplus", "Other"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    heating_type TEXT NOT NULL,
    area_m2 REAL NOT NULL,
    ceiling_height_m REAL,
    window_type TEXT,
    insulation_type TEXT,
    building_year INTEGER,
    climate_zone TEXT,
    target_temp_c REAL,
    burner_power_kw REAL,
    occupants INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pellets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    name TEXT,
    grade TEXT,
    bag_weight_kg REAL NOT NULL,
    price_per_bag REAL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    pellet_id INTEGER REFERENCES pellets(id) ON DELETE SET NULL,
    date TEXT NOT NULL,
    bags REAL,
    kg REAL NOT NULL,
    cost REAL,
    brand TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS entries_place_date ON entries(place_id, date);
"""

PLACE_FIELDS = {
    # name: (type, required)
    "name": (str, True),
    "heating_type": (str, True),
    "area_m2": (float, True),
    "ceiling_height_m": (float, False),
    "window_type": (str, False),
    "insulation_type": (str, False),
    "building_year": (int, False),
    "climate_zone": (str, False),
    "target_temp_c": (float, False),
    "burner_power_kw": (float, False),
    "occupants": (int, False),
    "notes": (str, False),
}
PELLET_FIELDS = {
    "brand": (str, True),
    "name": (str, False),
    "grade": (str, False),
    "bag_weight_kg": (float, True),
    "price_per_bag": (float, False),
    "notes": (str, False),
}
ENUMS = {
    "heating_type": HEATING_TYPES,
    "window_type": WINDOW_TYPES,
    "insulation_type": INSULATION_TYPES,
    "climate_zone": CLIMATE_ZONES,
}


class ValidationError(ValueError):
    pass


def connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _clean(data, fields, partial=False):
    out = {}
    for key, (kind, required) in fields.items():
        if key not in data:
            if required and not partial:
                raise ValidationError(f"'{key}' is required")
            continue
        value = data[key]
        if isinstance(value, str):
            value = value.strip()
        if value in ("", None):
            if required:
                raise ValidationError(f"'{key}' is required")
            out[key] = None
            continue
        try:
            value = kind(value)
        except (TypeError, ValueError):
            raise ValidationError(f"'{key}' must be a {'number' if kind is not str else 'text'}")
        if kind in (int, float) and value < 0:
            raise ValidationError(f"'{key}' cannot be negative")
        if key in ENUMS and value not in ENUMS[key]:
            raise ValidationError(f"'{key}' must be one of: {', '.join(ENUMS[key])}")
        out[key] = value
    if "area_m2" in out and not out["area_m2"]:
        raise ValidationError("'area_m2' must be greater than 0")
    if "bag_weight_kg" in out and not out["bag_weight_kg"]:
        raise ValidationError("'bag_weight_kg' must be greater than 0")
    return out


def _insert(conn, table, values):
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))
    conn.commit()
    return cur.lastrowid


def _update(conn, table, row_id, values):
    if values:
        sets = ", ".join(f"{k} = ?" for k in values)
        conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), row_id])
        conn.commit()


def _get(conn, table, row_id):
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def _delete(conn, table, row_id):
    cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    conn.commit()
    return cur.rowcount > 0


# Places ---------------------------------------------------------------

def list_places(conn):
    rows = conn.execute(
        """SELECT p.*, COUNT(e.id) AS entry_count, COALESCE(SUM(e.kg), 0) AS total_kg,
                  MAX(e.date) AS last_entry
           FROM places p LEFT JOIN entries e ON e.place_id = p.id
           GROUP BY p.id ORDER BY p.name COLLATE NOCASE"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_place(conn, place_id):
    return _get(conn, "places", place_id)


def create_place(conn, data):
    return get_place(conn, _insert(conn, "places", _clean(data, PLACE_FIELDS)))


def update_place(conn, place_id, data):
    if not get_place(conn, place_id):
        return None
    _update(conn, "places", place_id, _clean(data, PLACE_FIELDS, partial=True))
    return get_place(conn, place_id)


def delete_place(conn, place_id):
    return _delete(conn, "places", place_id)


# Pellets --------------------------------------------------------------

def list_pellets(conn):
    rows = conn.execute(
        """SELECT pe.*, COUNT(e.id) AS entry_count FROM pellets pe
           LEFT JOIN entries e ON e.pellet_id = pe.id
           GROUP BY pe.id ORDER BY pe.brand COLLATE NOCASE, pe.name COLLATE NOCASE"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["price_per_kg"] = (
            round(d["price_per_bag"] / d["bag_weight_kg"], 3) if d["price_per_bag"] is not None else None
        )
        out.append(d)
    return out


def get_pellet(conn, pellet_id):
    return _get(conn, "pellets", pellet_id)


def create_pellet(conn, data):
    return get_pellet(conn, _insert(conn, "pellets", _clean(data, PELLET_FIELDS)))


def update_pellet(conn, pellet_id, data):
    if not get_pellet(conn, pellet_id):
        return None
    _update(conn, "pellets", pellet_id, _clean(data, PELLET_FIELDS, partial=True))
    return get_pellet(conn, pellet_id)


def delete_pellet(conn, pellet_id):
    return _delete(conn, "pellets", pellet_id)


# Consumption entries ----------------------------------------------------

def _num(value, name):
    if value in ("", None):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"'{name}' must be a number")
    if value < 0:
        raise ValidationError(f"'{name}' cannot be negative")
    return value


def _clean_entry(conn, data, existing=None):
    """Work out kg and cost for an entry.

    Either `bags` (needs a pellet product) or `kg` must be given. Cost comes from an explicit
    `cost`, or from the pellet product's price at the time of logging, so later price changes
    do not rewrite history.
    """
    # Updates replace the whole entry (the form always sends every field); only the place is kept.
    merged = {"place_id": (existing or {}).get("place_id"), **data}
    place_id = merged.get("place_id")
    try:
        place_id = int(place_id)
    except (TypeError, ValueError):
        raise ValidationError("'place_id' is required")
    if not get_place(conn, place_id):
        raise ValidationError("place not found")

    raw_date = merged.get("date") or date.today().isoformat()
    try:
        entry_date = date.fromisoformat(str(raw_date)).isoformat()
    except ValueError:
        raise ValidationError("'date' must look like YYYY-MM-DD")

    pellet = None
    pellet_id = merged.get("pellet_id")
    if pellet_id not in ("", None):
        pellet = get_pellet(conn, int(pellet_id))
        if not pellet:
            raise ValidationError("pellet product not found")

    bags = _num(merged.get("bags"), "bags")
    kg = _num(merged.get("kg"), "kg")
    if kg is None and bags is not None:
        if not pellet:
            raise ValidationError("choose a pellet product to log by bags, or enter kg")
        kg = bags * pellet["bag_weight_kg"]
    if kg is None:
        raise ValidationError("enter the amount as bags or kg")
    if kg == 0:
        raise ValidationError("amount must be greater than 0")

    cost = _num(merged.get("cost"), "cost")
    if cost is None and pellet and pellet["price_per_bag"] is not None:
        cost = kg * pellet["price_per_bag"] / pellet["bag_weight_kg"]

    brand = pellet["brand"] + (f" {pellet['name']}" if pellet.get("name") else "") if pellet else None
    notes = merged.get("notes")
    return {
        "place_id": place_id,
        "pellet_id": pellet["id"] if pellet else None,
        "date": entry_date,
        "bags": bags,
        "kg": round(kg, 3),
        "cost": round(cost, 2) if cost is not None else None,
        "brand": brand or merged.get("brand") or None,
        "notes": notes.strip() if isinstance(notes, str) and notes.strip() else None,
    }


def list_entries(conn, place_id=None, season_from=None, season_to=None):
    sql = "SELECT e.*, p.name AS place_name FROM entries e JOIN places p ON p.id = e.place_id WHERE 1=1"
    args = []
    if place_id:
        sql += " AND e.place_id = ?"
        args.append(int(place_id))
    if season_from:
        sql += " AND e.date >= ?"
        args.append(season_from)
    if season_to:
        sql += " AND e.date <= ?"
        args.append(season_to)
    sql += " ORDER BY e.date DESC, e.id DESC"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def get_entry(conn, entry_id):
    return _get(conn, "entries", entry_id)


def create_entry(conn, data):
    return get_entry(conn, _insert(conn, "entries", _clean_entry(conn, data)))


def update_entry(conn, entry_id, data):
    existing = get_entry(conn, entry_id)
    if not existing:
        return None
    _update(conn, "entries", entry_id, _clean_entry(conn, data, existing))
    return get_entry(conn, entry_id)


def delete_entry(conn, entry_id):
    return _delete(conn, "entries", entry_id)
