"""Parse Segeln_am_Morgen.gpx -> web/public/data/track.json

Downsamples the 1s Strava track to ~5s and derives speed/heading per point.
"""
import json
import math
import os
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPX = os.path.join(ROOT, "Segeln_am_Morgen.gpx")
OUT = os.path.join(ROOT, "web", "public", "data", "track.json")

NS = {"g": "http://www.topografix.com/GPX/1/1"}
DOWNSAMPLE_S = 5


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def main():
    tree = ET.parse(GPX)
    pts = []
    for el in tree.getroot().iter("{%s}trkpt" % NS["g"]):
        lat = float(el.attrib["lat"])
        lon = float(el.attrib["lon"])
        ele_el = el.find("g:ele", NS)
        time_el = el.find("g:time", NS)
        ele = float(ele_el.text) if ele_el is not None else None
        t = time_el.text  # 2026-08-15T06:02:56Z
        pts.append((lat, lon, ele, t))

    # epoch seconds
    from datetime import datetime, timezone

    def parse_ts(s):
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()

    ts = [parse_ts(p[3]) for p in pts]
    t0 = ts[0]

    # downsample by time
    kept = []
    last_kept = -1e9
    for i, p in enumerate(pts):
        if ts[i] - last_kept >= DOWNSAMPLE_S or i == len(pts) - 1:
            kept.append(i)
            last_kept = ts[i]

    out = {"name": "Segeln am Morgen", "t0": pts[0][3], "points": []}
    total_dist = 0.0
    max_speed = 0.0
    for k, i in enumerate(kept):
        lat, lon, ele, t = pts[i]
        # speed/heading from neighbours in the *full* resolution series
        j0 = kept[k - 1] if k > 0 else i
        j1 = kept[k + 1] if k < len(kept) - 1 else i
        d = haversine_m(pts[j0][0], pts[j0][1], pts[j1][0], pts[j1][1])
        dt = max(ts[j1] - ts[j0], 1e-6)
        v = d / dt if j1 > j0 else 0.0
        hdg = bearing_deg(pts[j0][0], pts[j0][1], pts[j1][0], pts[j1][1]) if j1 > j0 else 0.0
        total_dist += haversine_m(pts[j0][0], pts[j0][1], lat, lon) if k > 0 else 0.0
        max_speed = max(max_speed, v)
        out["points"].append(
            {
                "t": round(ts[i] - t0, 1),
                "lat": lat,
                "lon": lon,
                "ele": ele,
                "speed": round(v, 3),
                "heading": round(hdg, 1),
            }
        )

    lats = [p["lat"] for p in out["points"]]
    lons = [p["lon"] for p in out["points"]]
    out["bounds"] = {
        "minLat": min(lats),
        "maxLat": max(lats),
        "minLon": min(lons),
        "maxLon": max(lons),
    }
    out["stats"] = {
        "nRaw": len(pts),
        "nKept": len(out["points"]),
        "durationS": round(ts[-1] - ts[0], 0),
        "distanceKm": round(total_dist / 1000.0, 2),
        "maxSpeedMs": round(max_speed, 2),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f)
    print("wrote", OUT)
    print(json.dumps(out["stats"], indent=2))
    print("bounds:", out["bounds"])


if __name__ == "__main__":
    main()
