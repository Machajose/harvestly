"""weather.py - humidity, rain and temperature for Eldoret from Open-Meteo (free, no key).

If the internet fails, it falls back to the last saved copy (weather_backup.json),
and finally to safe defaults, so a demo never breaks because of weather.
"""
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
LAT = os.getenv("WEATHER_LAT", "0.5143")
LON = os.getenv("WEATHER_LON", "35.2698")
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_backup.json")
REFRESH_SECONDS = 3 * 60 * 60  # ask Open-Meteo at most every 3 hours

DEFAULT = {"humidity": 65.0, "rain_mm": 10.0, "temp_c": 18.0, "source": "default"}
_memory = {"time": 0.0, "data": None}


def _average(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def fetch_weather():
    """Last 7 full days: average humidity, total rain, average temperature."""
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": LAT, "longitude": LON,
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


def get_weather_summary():
    """The function the rest of the project calls."""
    now = time.time()
    if _memory["data"] and now - _memory["time"] < REFRESH_SECONDS:
        return _memory["data"]
    try:
        data = fetch_weather()
        with open(BACKUP, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except Exception:
        try:
            with open(BACKUP, encoding="utf-8") as handle:
                data = json.load(handle)
            data["source"] = "backup"
        except Exception:
            data = dict(DEFAULT)
    _memory.update(time=now, data=data)
    return data


def effective_weather(sim):
    """Weather after the simulator overrides. Returns (humidity, rain_mm, temp_c, raw_weather).

    In the demo, the APEX Simulator page can force humidity and rain so you can
    make an alert fire on cue. Both the bot and the scheduler use this function.
    """
    w = get_weather_summary()
    humidity = sim["force_humidity"] if sim.get("force_humidity") is not None else w["humidity"]
    rain = sim["force_rain_mm"] if sim.get("force_rain_mm") is not None else w["rain_mm"]
    return humidity, rain, w["temp_c"], w


if __name__ == "__main__":
    print(get_weather_summary())
