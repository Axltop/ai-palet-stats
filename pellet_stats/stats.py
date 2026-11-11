"""Pure statistics functions. No database or HTTP code lives here, so it is easy to test."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta


def parse_date(value):
    return date.fromisoformat(value) if isinstance(value, str) else value


def season_of(d):
    """Heating seasons run from 1 July to 30 June and are labelled like '2025/26'."""
    d = parse_date(d)
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def season_bounds(label):
    start = int(label.split("/")[0])
    return date(start, 7, 1), date(start + 1, 6, 30)


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def _ratio(numerator, denominator, digits=2):
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, digits)


def filter_season(entries, season):
    if not season:
        return list(entries)
    return [e for e in entries if season_of(e["date"]) == season]


def place_stats(place, entries, season=None):
    """Statistics for one place.

    `place` is a dict with at least area_m2 and ceiling_height_m.
    `entries` are dicts with date (ISO string), kg, cost (may be None) and brand (may be None).
    Each entry is the amount of pellets burned (loaded into the burner) on that date.
    """
    all_seasons = sorted({season_of(e["date"]) for e in entries})
    entries = sorted(filter_season(entries, season), key=lambda e: e["date"])
    area = place.get("area_m2") or 0
    height = place.get("ceiling_height_m") or 0
    volume = area * height if area and height else None

    total_kg = sum(e["kg"] for e in entries)
    costs = [e["cost"] for e in entries if e.get("cost") is not None]
    total_cost = sum(costs) if costs else None
    kg_with_cost = sum(e["kg"] for e in entries if e.get("cost") is not None)

    first = parse_date(entries[0]["date"]) if entries else None
    last = parse_date(entries[-1]["date"]) if entries else None
    days_span = (last - first).days + 1 if entries else 0

    daily = defaultdict(lambda: {"kg": 0.0, "cost": 0.0})
    monthly = defaultdict(lambda: {"kg": 0.0, "cost": 0.0, "entries": 0})
    seasons = defaultdict(lambda: {"kg": 0.0, "cost": 0.0, "entries": 0, "first": None, "last": None})
    brands = defaultdict(lambda: {"kg": 0.0, "cost": 0.0, "kg_with_cost": 0.0})

    for e in entries:
        d = parse_date(e["date"])
        cost = e.get("cost") or 0.0
        daily[d.isoformat()]["kg"] += e["kg"]
        daily[d.isoformat()]["cost"] += cost
        m = monthly[d.strftime("%Y-%m")]
        m["kg"] += e["kg"]
        m["cost"] += cost
        m["entries"] += 1
        s = seasons[season_of(d)]
        s["kg"] += e["kg"]
        s["cost"] += cost
        s["entries"] += 1
        s["first"] = min(s["first"], d) if s["first"] else d
        s["last"] = max(s["last"], d) if s["last"] else d
        b = brands[e.get("brand") or "Unspecified"]
        b["kg"] += e["kg"]
        b["cost"] += cost
        if e.get("cost") is not None:
            b["kg_with_cost"] += e["kg"]

    # Fill in days with no burning so the daily chart shows gaps honestly.
    daily_series = []
    if entries:
        d = first
        while d <= last:
            v = daily.get(d.isoformat(), {"kg": 0.0, "cost": 0.0})
            daily_series.append({"date": d.isoformat(), "kg": _round(v["kg"]), "cost": _round(v["cost"])})
            d += timedelta(days=1)

    monthly_series = []
    for key in sorted(monthly):
        v = monthly[key]
        y, mo = map(int, key.split("-"))
        month_start, month_end = date(y, mo, 1), date(y, mo, monthrange(y, mo)[1])
        # Only count days inside the logged period, so a half-logged first month is not diluted.
        active_days = (min(month_end, last) - max(month_start, first)).days + 1
        monthly_series.append({
            "month": key,
            "kg": _round(v["kg"]),
            "cost": _round(v["cost"]),
            "entries": v["entries"],
            "days": active_days,
            "kg_per_day": _ratio(v["kg"], active_days),
            "kg_per_m2": _ratio(v["kg"], area, 3),
        })

    season_series = []
    for key in sorted(seasons):
        v = seasons[key]
        days = (v["last"] - v["first"]).days + 1
        season_series.append({
            "season": key,
            "kg": _round(v["kg"]),
            "cost": _round(v["cost"]),
            "entries": v["entries"],
            "first": v["first"].isoformat(),
            "last": v["last"].isoformat(),
            "days": days,
            "kg_per_day": _ratio(v["kg"], days),
            "kg_per_m2": _ratio(v["kg"], area),
            "cost_per_m2": _ratio(v["cost"], area),
        })

    brand_series = [
        {
            "brand": name,
            "kg": _round(v["kg"]),
            "cost": _round(v["cost"]),
            "price_per_kg": _ratio(v["cost"], v["kg_with_cost"], 3),
            "share": _ratio(v["kg"] * 100, total_kg, 1),
        }
        for name, v in sorted(brands.items(), key=lambda kv: -kv[1]["kg"])
    ]

    if not entries:
        total_kg = None  # no data is not the same as zero consumption
    return {
        "season": season,
        "available_seasons": all_seasons,
        "summary": {
            "entries": len(entries),
            "total_kg": _round(total_kg) if entries else 0,
            "total_cost": _round(total_cost),
            "first_date": first.isoformat() if first else None,
            "last_date": last.isoformat() if last else None,
            "days": days_span,
            "kg_per_day": _ratio(total_kg, days_span),
            "cost_per_day": _ratio(total_cost, days_span),
            "kg_per_m2": _ratio(total_kg, area),
            "kg_per_m3": _ratio(total_kg, volume),
            "cost_per_m2": _ratio(total_cost, area),
            "kg_per_m2_per_day": _ratio(total_kg, area * days_span if area else 0, 4),
            "price_per_kg": _ratio(total_cost, kg_with_cost, 3),
        },
        "daily": daily_series,
        "monthly": monthly_series,
        "seasons": season_series,
        "brands": brand_series,
    }


def compare_places(places_with_entries, season=None):
    """Side by side summary for several places. Input: list of (place, entries)."""
    rows = []
    for place, entries in places_with_entries:
        s = place_stats(place, entries, season)["summary"]
        rows.append({
            "place_id": place["id"],
            "name": place["name"],
            "heating_type": place.get("heating_type"),
            "area_m2": place.get("area_m2"),
            "insulation_type": place.get("insulation_type"),
            "window_type": place.get("window_type"),
            **s,
        })
    return rows
