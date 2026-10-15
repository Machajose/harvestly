"""weather.py - humidity, rain and temperature from Open-Meteo (free, no key).

Weather is looked up per sub-county of Uasin Gishu (the farmer's sub-county), and for Eldoret town
when the sub-county is unknown. Each place is fetched at most every 3 hours.

If the internet fails, a place falls back to its last saved copy (weather_backup*.json), then to the
Eldoret data, and finally to safe defaults, so a demo never breaks because of weather.
"""
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
LAT = os.getenv("WEATHER_LAT", "0.5143")
LON = os.getenv("WEATHER_LON", "35.2698")
HERE = os.path.dirname(os.path.abspath(__file__))
REFRESH_SECONDS = 3 * 60 * 60  # ask Open-Meteo at most every 3 hours per place

# APPROXIMATE centre points of the Uasin Gishu sub-counties (latitude, longitude). They were written
# from general knowledge, NOT surveyed: check each one on a map and correct it before relying on it.
# Open-Meteo's grid is roughly 10 km wide, so nearby places can still return similar numbers.
SUB_COUNTY_COORDS = {
    "soy": (0.72, 35.10),
    "turbo": (0.63, 35.05),
    "moiben": (0.60, 35.36),
    "kesses": (0.38, 35.28),
    "kapseret": (0.47, 35.33),
    "ainabkoi": (0.45, 35.42),
}

DEFAULT = {"humidity": 65.0, "rain_mm": 10.0, "temp_c": 18.0, "source": "default"}
_memory = {}   # place key -> {"time": float, "data": dict}


def place_key(place):
    """'Soy ' -> 'soy'. Anything we do not know becomes 'default' (Eldoret)."""
    key = (place or "").strip().lower()
    return key if key in SUB_COUNTY_COORDS else "default"


def coords_for(place):
    key = place_key(place)
    if key == "default":
        return LAT, LON
    return SUB_COUNTY_COORDS[key]


def _backup_file(key):
    name = "weather_backup.json" if key == "default" else f"weather_backup_{key}.json"
    return os.path.join(HERE, name)


def _average(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def fetch_weather(lat=None, lon=None):
    """Last 7 full days: average humidity, total rain, average temperature."""
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": lat if lat is not None else LAT,
                "longitude": lon if lon is not None else LON,
                "hourly": "relative_humidity_2m,precipitation,temperature_2m",
                "past_days": 7, "forecast_days": 1, "timezone": "Africa/Nairobi"},
        timeout=15)
    resp.raise_for_status()
    hourly = resp.json()["hourly"]
    last = 7 * 24  # the first 168 hours = the past 7 full days
    return {
        "humidity": _average(hourly["relative_humidity_2m"][:last]),
        "rain_mm": sum(v for v in hourly["precipitation"][:last] if v is not None),
        "temp_c": _average(hourly["temperature_2m"][:last]),
        "source": "open-meteo",
    }


def get_weather_summary(place=None):
    """The function the rest of the project calls. `place` is a sub-county name, or None for Eldoret."""
    key = place_key(place)
    now = time.time()
    cached = _memory.get(key)
    if cached and now - cached["time"] < REFRESH_SECONDS:
        return cached["data"]
    lat, lon = coords_for(place)
    try:
        data = fetch_weather(lat, lon)
        with open(_backup_file(key), "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except Exception:
        try:
            with open(_backup_file(key), encoding="utf-8") as handle:
                data = json.load(handle)
            data["source"] = "backup"
        except Exception:
            # no copy for this sub-county: borrow Eldoret's weather (still better than a made-up default)
            data = dict(get_weather_summary(None)) if key != "default" else dict(DEFAULT)
            if key != "default":
                data["source"] = "eldoret-fallback"
    data["place"] = key
    _memory[key] = {"time": now, "data": data}
    return data


def effective_weather(sim, place=None):
    """Weather after the simulator overrides. Returns (humidity, rain_mm, temp_c, raw_weather).

    In the demo, the APEX Simulator page can force humidity and rain so you can
    make an alert fire on cue. The forced values apply to every sub-county.
    Both the bot and the scheduler use this function.
    """
    w = get_weather_summary(place)
    humidity = sim["force_humidity"] if sim.get("force_humidity") is not None else w["humidity"]
    rain = sim["force_rain_mm"] if sim.get("force_rain_mm") is not None else w["rain_mm"]
    return humidity, rain, w["temp_c"], w


if __name__ == "__main__":
    print("Eldoret:", get_weather_summary())
    for name in SUB_COUNTY_COORDS:
        print(name.title() + ":", get_weather_summary(name))
