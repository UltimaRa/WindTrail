"""Fetch terrain + land-cover data -> data/terrain.bin, data/geo.json

- Elevation: AWS Terrarium tiles (z13, ~19 m/px at this latitude), decoded as
  h = R*256 + G + B/256 - 32768, mosaicked, cropped to BBOX, resampled to a
  256x256 Float32 grid (row-major, north-to-south, west-to-east).
- Land cover: OpenStreetMap via Overpass (forest/wood polygons, and the
  Grosser Mueggelsee water polygon as a bonus), saved as coordinate rings.
"""
import io
import json
import math
import os

import numpy as np
import requests
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

BBOX = {"minLat": 52.395, "maxLat": 52.475, "minLon": 13.59, "maxLon": 13.72}
GRID = 256
TILE_Z = 13
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png"
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def lon_to_tilex(lon, z):
    return int(math.floor((lon + 180.0) / 360.0 * (1 << z)))


def lat_to_tiley(lat, z):
    r = math.radians(lat)
    return int(math.floor((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * (1 << z)))


def tilex_to_lon(x, z):
    return x / (1 << z) * 360.0 - 180.0


def tiley_to_lat(y, z):
    n = math.pi - 2.0 * math.pi * y / (1 << z)
    return math.degrees(math.atan(math.sinh(n)))


def fetch_elevation():
    x0, x1 = lon_to_tilex(BBOX["minLon"], TILE_Z), lon_to_tilex(BBOX["maxLon"], TILE_Z)
    # note: tile y increases southward; maxLat -> smaller y
    y0, y1 = lat_to_tiley(BBOX["maxLat"], TILE_Z), lat_to_tiley(BBOX["minLat"], TILE_Z)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    print("tiles: x %d-%d, y %d-%d (%dx%d)" % (x0, x1, y0, y1, nx, ny))
    mosaic = np.zeros((ny * 256, nx * 256), dtype=np.float32)
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            url = TERRARIUM % (TILE_Z, tx, ty)
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            im = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype(np.float32)
            h = im[..., 0] * 256.0 + im[..., 1] + im[..., 2] / 256.0 - 32768.0
            mosaic[(ty - y0) * 256:(ty - y0 + 1) * 256,
                   (tx - x0) * 256:(tx - x0 + 1) * 256] = h
    # crop mosaic to exact bbox
    west = tilex_to_lon(x0, TILE_Z)
    north = tiley_to_lat(y0, TILE_Z)
    east = tilex_to_lon(x1 + 1, TILE_Z)
    south = tiley_to_lat(y1 + 1, TILE_Z)
    px_per_deg_lon = mosaic.shape[1] / (east - west)
    px_per_deg_lat = mosaic.shape[0] / (north - south)
    c0 = int(round((BBOX["minLon"] - west) * px_per_deg_lon))
    c1 = int(round((BBOX["maxLon"] - west) * px_per_deg_lon))
    r0 = int(round((north - BBOX["maxLat"]) * px_per_deg_lat))
    r1 = int(round((north - BBOX["minLat"]) * px_per_deg_lat))
    crop = mosaic[r0:r1, c0:c1]
    # resample to GRID x GRID with PIL bilinear
    im = Image.fromarray(crop, mode="F").resize((GRID, GRID), Image.BILINEAR)
    grid = np.asarray(im, dtype=np.float32)
    print("elevation grid: %dx%d, min %.1f m, max %.1f m"
          % (grid.shape[0], grid.shape[1], grid.min(), grid.max()))
    return grid


def fetch_osm():
    q = """
[out:json][timeout:90];
(
  way["natural"="water"](%(minLat)s,%(minLon)s,%(maxLat)s,%(maxLon)s);
  relation["natural"="water"](%(minLat)s,%(minLon)s,%(maxLat)s,%(maxLon)s);
  way["landuse"="forest"](%(minLat)s,%(minLon)s,%(maxLat)s,%(maxLon)s);
  relation["landuse"="forest"](%(minLat)s,%(minLon)s,%(maxLat)s,%(maxLon)s);
  way["natural"="wood"](%(minLat)s,%(minLon)s,%(maxLat)s,%(maxLon)s);
  relation["natural"="wood"](%(minLat)s,%(minLon)s,%(maxLat)s,%(maxLon)s);
);
out geom;
""" % BBOX
    last_err = None
    for url in OVERPASS_MIRRORS:
        for attempt in range(3):
            try:
                r = requests.post(
                    url,
                    data=("data=" + requests.utils.quote(q)).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=150,
                )
                r.raise_for_status()
                elements = r.json()["elements"]
                break
            except Exception as e:
                print("overpass failed (%s, attempt %d): %s" % (url, attempt + 1, e))
                last_err = e
                if "429" in str(e) or "504" in str(e) or "timeout" in str(e).lower():
                    import time
                    time.sleep(20 * (attempt + 1))
                    continue
                break
        else:
            continue
        break
    else:
        raise last_err
    waters, forests = [], []
    for el in elements:
        tags = el.get("tags", {})
        is_water = tags.get("natural") == "water"
        if el["type"] == "way":
            rings = [el["geometry"]]
        elif el["type"] == "relation":
            rings = stitch_relation(el)
        else:
            continue
        target = waters if is_water else forests
        for ring in rings:
            coords = [(p["lat"], p["lon"]) for p in ring]
            if len(coords) >= 3:
                target.append(coords)
    # Grosser Mueggelsee = largest water ring by area; keep all water rings
    def ring_area(ring):
        return abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1]
                       - ring[(i + 1) % len(ring)][0] * ring[i][1]
                       for i in range(len(ring))))
    waters.sort(key=ring_area, reverse=True)
    print("OSM: %d water rings (largest = lake), %d forest rings"
          % (len(waters), len(forests)))
    return waters, forests


def stitch_relation(rel):
    """Join outer way geometries of a relation into closed rings."""
    segs = []
    for m in rel.get("members", []):
        if m.get("type") == "way" and m.get("role") in ("outer", "") and "geometry" in m:
            g = [(p["lat"], p["lon"]) for p in m["geometry"]]
            if g:
                segs.append(g)
    rings = []
    while segs:
        ring = segs.pop(0)
        merged = True
        while merged and ring[0] != ring[-1]:
            merged = False
            for i, s in enumerate(segs):
                if ring[-1] == s[0]:
                    ring = ring + s[1:]
                elif ring[-1] == s[-1]:
                    ring = ring + s[-2::-1]
                elif ring[0] == s[-1]:
                    ring = s[:-1] + ring
                elif ring[0] == s[0]:
                    ring = s[1::-1] + ring
                else:
                    continue
                segs.pop(i)
                merged = True
                break
        if len(ring) >= 3:
            rings.append(ring)
    return rings


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    grid = fetch_elevation()
    grid.tofile(os.path.join(DATA, "terrain.bin"))

    lakes, forests = [], []
    try:
        lakes, forests = fetch_osm()
    except Exception as e:
        print("Overpass failed (%s); continuing with elevation-only masks" % e)

    meta = {
        "bbox": BBOX,
        "grid": GRID,
        "lakeLevel": 32.3,
        "lakes": lakes,
        "forests": forests,
    }
    with open(os.path.join(DATA, "geo.json"), "w") as f:
        json.dump(meta, f)
    print("wrote terrain.bin (%d bytes) and geo.json" % (GRID * GRID * 4))
