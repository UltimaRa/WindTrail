"""Fetch wind observations for 2026-08-15 -> data/wind_obs.json

Sources:
- DWD Climate Data Center, 10-minute station wind (00427 Berlin-Schoenefeld,
  00433 Berlin-Tempelhof), "recent" zip files.
- Open-Meteo Historical Forecast API (ICON-D2, 2.2 km) hourly at three points
  across Grosser Mueggelsee.
"""
import io
import json
import os
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "wind_obs.json")

DATE = "20260815"
DWD_BASE = (
    "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
    "climate/10_minutes/wind/recent"
)
STATIONS = ["00427", "00433"]

# north / center / south of Grosser Mueggelsee
OM_POINTS = [
    {"name": "north", "lat": 52.460, "lon": 13.652},
    {"name": "center", "lat": 52.440, "lon": 13.657},
    {"name": "south", "lat": 52.423, "lon": 13.660},
]


def fetch_dwd_station(station_id):
    url = "%s/10minutenwerte_wind_%s_akt.zip" % (DWD_BASE, station_id)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    txt_name = [n for n in z.namelist() if n.startswith("produkt_zehn_min_ff")][0]
    rows = []
    with z.open(txt_name) as f:
        for line in io.TextIOWrapper(f, encoding="latin-1"):
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 5 or parts[0] == "STATIONS_ID":
                continue
            if not parts[1].startswith(DATE):
                continue
            # STATIONS_ID; MESS_DATUM(UTC); QN; FF_10 (m/s); DD_10 (deg); eor
            try:
                speed = float(parts[3])
                direction = float(parts[4])
            except ValueError:
                continue
            if speed < 0 or direction < 0:
                continue
            rows.append({"t": parts[1], "speed": speed, "dir": direction})
    return rows


def fetch_station_coords():
    """Best-effort station metadata; falls back to hardcoded coordinates."""
    coords = {
        "00427": {"name": "Berlin-Schoenefeld", "lat": 52.3807, "lon": 13.5225},
        "00433": {"name": "Berlin-Tempelhof", "lat": 52.4675, "lon": 13.4021},
    }
    try:
        url = "%s/zehn_min_ff_Beschreibung_Stationen.txt" % DWD_BASE
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        for line in r.text.splitlines():
            sid = line[:5].strip()
            if sid in coords and len(line) > 60:
                # fixed-width: id, from, to, height, lat, lon, name, state
                segs = line.split()
                # find lat/lon as the two floats before the name
                floats = [s for s in segs if _is_float(s)]
                if len(floats) >= 3:
                    coords[sid]["lat"] = float(floats[-3])
                    coords[sid]["lon"] = float(floats[-2])
    except Exception as e:
        print("station metadata fetch failed, using fallback:", e)
    return coords


def _is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def fetch_openmeteo():
    points = []
    for p in OM_POINTS:
        url = (
            "https://historical-forecast-api.open-meteo.com/v1/forecast"
            "?latitude=%(lat).4f&longitude=%(lon).4f"
            "&start_date=2026-08-15&end_date=2026-08-15"
            "&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m"
            "&wind_speed_unit=ms&timezone=UTC&models=icon_d2" % p
        )
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        h = r.json()["hourly"]
        points.append(
            {
                "name": p["name"],
                "lat": p["lat"],
                "lon": p["lon"],
                "time": h["time"],
                "speed": h["wind_speed_10m"],
                "dir": h["wind_direction_10m"],
                "gust": h["wind_gusts_10m"],
            }
        )
    return points


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    coords = fetch_station_coords()
    dwd = {}
    for sid in STATIONS:
        rows = fetch_dwd_station(sid)
        dwd[sid] = dict(coords[sid])
        dwd[sid]["series"] = rows
        print("DWD", sid, coords[sid]["name"], "rows:", len(rows))

    om = fetch_openmeteo()
    for p in om:
        print("Open-Meteo", p["name"], "hours:", len(p["time"]))

    out = {
        "date": "2026-08-15",
        "dwd": dwd,
        "openmeteo": om,
    }
    with open(OUT, "w") as f:
        json.dump(out, f)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
