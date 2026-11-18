"""Daily temperatures from OpenWeather, cached in the database. Standard library only.

Uses two OpenWeather APIs:
- Geocoding (free with any key) to turn a town name into coordinates.
- One Call API 3.0 "day_summary" for the temperatures of a past day. This needs the
  "One Call by Call" subscription on your OpenWeather account (the first 1,000 calls a day are free).

The API key is read from the OPENWEATHER_API_KEY environment variable, from a `.env` file in the
folder you start the app from, or from the --openweather-key option. It is never stored in the database.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from . import db

BASE_URL = "https://api.openweathermap.org"
# Days fetched per request to the app, so one click never makes hundreds of calls at once.
FETCH_BATCH = 60


class WeatherError(Exception):
    pass


def find_api_key(explicit=None, env=os.environ, dotenv=Path(".env")):
    if explicit:
        return explicit.strip()
    if env.get("OPENWEATHER_API_KEY"):
        return env["OPENWEATHER_API_KEY"].strip()
    try:
        for line in Path(dotenv).read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "OPENWEATHER_API_KEY" and value.strip():
                return value.strip().strip("'\"")
    except OSError:
        pass
    return None


def daily_mean(temperature):
    """Mean temperature of a day from OpenWeather's day_summary `temperature` block.

    The average of the morning, afternoon, evening and night readings is closer to the true daily
    mean than (min + max) / 2, so that is used when all four are there.
    """
    parts = [temperature.get(k) for k in ("morning", "afternoon", "evening", "night")]
    if all(p is not None for p in parts):
        return round(sum(parts) / 4, 2)
    if temperature.get("min") is not None and temperature.get("max") is not None:
        return round((temperature["min"] + temperature["max"]) / 2, 2)
    return None


class OpenWeather:
    def __init__(self, api_key, opener=urlopen, base_url=BASE_URL, timeout=15):
        self.api_key = api_key
        self.opener = opener
        self.base_url = base_url
        self.timeout = timeout

    def _get(self, path, params):
        url = f"{self.base_url}{path}?{urlencode({**params, 'appid': self.api_key})}"
        try:
            with self.opener(url, timeout=self.timeout) as res:
                return json.loads(res.read())
        except HTTPError as exc:
            if exc.code == 401:
                raise WeatherError(
                    "OpenWeather refused the API key. Daily temperatures need the One Call API 3.0 "
                    "(“One Call by Call”) subscription on your OpenWeather account; a new key can also "
                    "take up to a couple of hours to start working."
                )
            if exc.code == 429:
                raise WeatherError("OpenWeather says the daily call limit is reached. Try again tomorrow.")
            raise WeatherError(f"OpenWeather returned an error ({exc.code}).")
        except (URLError, TimeoutError, OSError) as exc:
            raise WeatherError(f"Could not reach OpenWeather: {getattr(exc, 'reason', exc)}")
        except ValueError:
            raise WeatherError("OpenWeather sent a reply that is not JSON.")

    def geocode(self, query, limit=5):
        rows = self._get("/geo/1.0/direct", {"q": query, "limit": limit})
        return [
            {"name": r.get("name"), "state": r.get("state"), "country": r.get("country"),
             "lat": round(r["lat"], 4), "lon": round(r["lon"], 4)}
            for r in rows if "lat" in r and "lon" in r
        ]

    def day_summary(self, lat, lon, day):
        data = self._get("/data/3.0/onecall/day_summary",
                         {"lat": lat, "lon": lon, "date": str(day), "units": "metric"})
        t = data.get("temperature") or {}
        return {"mean": daily_mean(t), "min": t.get("min"), "max": t.get("max")}


def clamp_period(start, end, today=None):
    """Past days only: today is not over yet and the future is a forecast."""
    yesterday = (today or date.today()) - timedelta(days=1)
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    return start, min(end, yesterday)


def missing_days(conn, lat, lon, start, end, today=None):
    start, end = clamp_period(start, end, today)
    have = db.get_temperatures(conn, lat, lon, start, end)
    out = []
    d = start
    while d <= end:
        if d.isoformat() not in have:
            out.append(d)
        d += timedelta(days=1)
    return out


def fetch_missing(conn, client, lat, lon, start, end, limit=FETCH_BATCH, today=None):
    """Fetch up to `limit` days that are not cached yet. Returns how many were fetched and how many remain."""
    todo = missing_days(conn, lat, lon, start, end, today)
    for day in todo[:limit]:
        t = client.day_summary(lat, lon, day)
        db.save_temperature(conn, lat, lon, day, t["mean"], t["min"], t["max"])
    done = min(limit, len(todo))
    return {"fetched": done, "remaining": len(todo) - done}
