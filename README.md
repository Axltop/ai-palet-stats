# Pellet Stats

A small local web app for tracking how many pellets your burner uses, what it costs, and how your places compare.

- **Places**: define one or more places (house, flat, cottage) with heating type (floor heating, radiators, direct pellet burner/stove, or mixed), heated area, ceiling height, window type, insulation, year built, climate zone, target temperature, burner power and occupants.
- **Pellets**: keep a list of the pellets you buy: brand, product, grade (ENplus A1/A2, DINplus), bag weight and price per bag.
- **Consumption log**: log what you put into the burner, in bags or kg. The cost is worked out from the pellet price at the time you log it, so changing a price later does not rewrite your history. You can also type the cost by hand.
- **Statistics per place**: kg and cost per day, per month and per heating season (1 July to 30 June), kg per m², kg per m³, grams per m² per day, cost per m², average price per kg, and a breakdown by pellet brand. Charts for monthly and daily consumption.
- **Comparison**: a table and charts comparing all places for a season or all time. "g / m² / day" divides by area and by the days logged, so places with different sizes and logging periods compare fairly.
- **Storage**: record the bags you buy or put into storage (by bags or kg, with what you paid). Each place shows what is left: bags put in minus what you logged as burned since the first delivery, per pellet product.
- **Outdoor temperatures** from OpenWeather: give a place its location, then pick any period to see its mean daily temperature, coldest and warmest day, heating degree days and kg burned per degree day, with a chart of daily kg against temperature. The monthly table shows the same per month.
- **CSV export** of the log.

## Run it

You only need Python 3.9 or newer. There is nothing to install.

```bash
git clone https://github.com/Axltop/ai-palet-stats.git
cd ai-palet-stats
python3 -m pellet_stats
```

Then open <http://127.0.0.1:8000>.

To try it with sample data (three places and about a year of entries), use a separate database file:

```bash
python3 -m pellet_stats --db demo.db --demo
```

Options:

| Option | Default | What it does |
| --- | --- | --- |
| `--db FILE` | `pellets.db` | SQLite file where your data is stored |
| `--port N` | `8000` | Port to listen on |
| `--host ADDR` | `127.0.0.1` | Use `0.0.0.0` to open it from your phone on the same network |
| `--demo` | off | Add sample data if the database has no places yet |
| `--openweather-key KEY` | none | OpenWeather API key (see below) |

Your data lives in the SQLite file. Back it up by copying that file.

## Outdoor temperatures (OpenWeather)

Daily temperatures come from OpenWeather's [One Call API 3.0](https://openweathermap.org/api/one-call-3) `day_summary`. That API needs the **"One Call by Call"** subscription on your OpenWeather account. The first 1,000 calls a day are free, but OpenWeather asks for a card when you subscribe. A plain free key is enough only for the town lookup.

Give the app your key in one of these ways (the first one found wins). The key is never stored in the database, and `.env` is ignored by git.

```bash
python3 -m pellet_stats --openweather-key YOUR_KEY       # 1. option
OPENWEATHER_API_KEY=YOUR_KEY python3 -m pellet_stats     # 2. environment variable
echo "OPENWEATHER_API_KEY=YOUR_KEY" > .env               # 3. .env file in the folder you start the app from
```

Then edit a place, type its town and press **Find coordinates** (or type the latitude and longitude), and open the place. Press **Get missing days** in the Outdoor temperature card. Each day is one API call and is saved, so a day is only fetched once; a full season is about 365 calls.

- The **mean daily temperature** is the average of OpenWeather's morning, afternoon, evening and night readings for that day.
- **Heating degree days** use the Eurostat method: 18 °C minus the day's mean, for days at 15 °C or colder. **kg per degree day** stays about the same from mild to cold months if the house behaves the same, so it is a fair way to compare winters or to see if insulation work paid off.

## How to log

Each entry is the amount of pellets you burned (put into the burner) on that date. Log every refill, whether that is daily or every few days. Daily totals are then spiky, so the monthly **kg / day** figure is the one to watch: it divides each month's total by the days inside the logged period.

The currency symbol is set in the top right and is only a display setting.

## Run the tests

```bash
python3 -m unittest
```

## How it is built

- `pellet_stats/server.py`: HTTP server and JSON API, Python standard library only
- `pellet_stats/db.py`: SQLite schema, validation and queries
- `pellet_stats/stats.py`: the statistics, as pure functions
- `pellet_stats/weather.py`: OpenWeather client and the temperature cache
- `pellet_stats/demo.py`: sample data
- `pellet_stats/static/`: the single page front end (plain HTML, CSS and JavaScript, charts are inline SVG)

### API

| Method | Path | |
| --- | --- | --- |
| GET, POST | `/api/places` | list, create |
| GET, PUT, DELETE | `/api/places/{id}` | read, update, delete (deletes its entries too) |
| GET | `/api/places/{id}/stats?season=2025/26` | statistics, season optional |
| GET | `/api/compare?season=2025/26` | comparison of all places |
| GET, POST | `/api/pellets` | list, create |
| PUT, DELETE | `/api/pellets/{id}` | update, delete |
| GET, POST | `/api/entries?place_id=1` | list, create (`bags` with `pellet_id`, or `kg`) |
| GET, PUT, DELETE | `/api/entries/{id}` | read, update, delete |
| GET | `/api/export.csv?place_id=1` | CSV export |
| GET | `/api/options` | allowed values for the dropdowns |
