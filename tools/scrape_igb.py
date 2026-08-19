"""Scrape the IGB emon 7-day wind speed plot -> data/igb_lake_wind.json

The raw 15-min data sits behind the emon login, so the mean-speed and gust
curves are extracted from the pre-rendered 07-ws plot PNG (black plot area,
yellow = Windgeschwindigkeit/mean, azure = Boen/gust; y axis 0..25 m/s with
tick labels at rows 201/168/133/100/65/31 for 0/5/10/15/20/25).

x calibration: px/day is known from the vertical day gridlines (~57.4), the
offset is found by cross-correlating the scraped mean-speed curve against the
DWD 10-min record (Schoenefeld) over the whole week.

The companion direction plot (07-wr) proved too noisy for reliable pixel
extraction (thick jumping band, wrap-around segments); direction is therefore
taken from DWD + ICON-D2 in build_field.py. Only speed + gust are exported.
"""
import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BASE = "https://emon.igb-berlin.de/"
WS_PAGE = "windgeschwindigkeit-ms.html"
CEST = timezone(timedelta(hours=2))
DWD_ZIP = ("https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
           "climate/10_minutes/wind/recent/10minutenwerte_wind_00427_akt.zip")

WS_LEGEND = (28, 75, 410, 570)  # legend box overlapping the plot corner
# y mapping from tick labels: 0 m/s at row 201, 25 m/s at row 31
WS_Y0, WS_Y25 = 201.0, 31.0


def load_plot():
    html = requests.get(BASE + WS_PAGE, timeout=30).text
    m = re.findall(r'assets/images/[^"]*07-ws-[a-z0-9]+\.png', html)
    if not m:
        raise RuntimeError("07-ws plot URL not found")
    r = requests.get(BASE + m[0], timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def azure_mask(a):
    r = a[..., 0].astype(int)
    g = a[..., 1].astype(int)
    b = a[..., 2].astype(int)
    return (b > 180) & (g > 80) & (g < 210) & (r < 100)


def yellow_mask(a):
    r = a[..., 0].astype(int)
    g = a[..., 1].astype(int)
    b = a[..., 2].astype(int)
    return (r > 200) & (g > 200) & (b < 100)


def curve_columns(mask, clip, exclude):
    r0, r1, c0, c1 = clip
    m = np.zeros_like(mask)
    m[r0:r1 + 1, c0:c1 + 1] = mask[r0:r1 + 1, c0:c1 + 1]
    er0, er1, ec0, ec1 = exclude
    m[er0:er1, ec0:ec1] = False
    cols = {}
    for x in range(c0, c1 + 1):
        ys = np.where(m[:, x])[0]
        if ys.size:
            cols[x] = float(np.median(ys))
    return cols


def dwd_week():
    cache = os.path.join(DATA, "dwd_wind_00427.zip")
    if not os.path.exists(cache):
        r = requests.get(DWD_ZIP, timeout=60)
        r.raise_for_status()
        open(cache, "wb").write(r.content)
    z = zipfile.ZipFile(cache)
    name = [n for n in z.namelist() if n.startswith("produkt_zehn_min_ff")][0]
    ts, sp = [], []
    with z.open(name) as f:
        for line in io.TextIOWrapper(f, encoding="latin-1"):
            p = [x.strip() for x in line.split(";")]
            if len(p) < 5 or not p[1].isdigit():
                continue
            if not ("20260810" <= p[1] <= "20260818"):
                continue
            try:
                s = float(p[3])
            except ValueError:
                continue
            if s < 0:
                continue
            ts.append(datetime.strptime(p[1], "%Y%m%d%H%M")
                      .replace(tzinfo=timezone.utc).timestamp())
            sp.append(s)
    return np.array(ts), np.array(sp)


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    img = load_plot()
    a = np.asarray(img)
    black = a.max(axis=2) < 60
    h, w = black.shape
    cols_b = np.where(black.sum(axis=0) > 0.45 * h)[0]
    rows_b = np.where(black.sum(axis=1) > 0.45 * w)[0]
    clip = (rows_b.min(), rows_b.max(), cols_b.min(), cols_b.max())
    print("plot area rows %d-%d cols %d-%d" % clip)

    y_to_ms = lambda row: (WS_Y0 - row) * 25.0 / (WS_Y0 - WS_Y25)
    mean_cols = curve_columns(yellow_mask(a), clip, WS_LEGEND)
    gust_cols = curve_columns(azure_mask(a), clip, WS_LEGEND)
    print("mean %d cols (%d..%d), gust %d cols"
          % (len(mean_cols), min(mean_cols), max(mean_cols), len(gust_cols)))

    dwd_t, dwd_s = dwd_week()
    col_arr = np.array(sorted(mean_cols), dtype=float)
    val_arr = np.array([y_to_ms(mean_cols[c]) for c in col_arr])

    # offset search with gridline-derived px/day
    best = None
    now_ts = datetime.now(CEST).timestamp()
    for ppd in np.arange(56.5, 58.6, 0.25):
        spp = 86400.0 / ppd
        for off_h in np.arange(-26.0, 26.01, 1.0 / 6.0):
            t_curve = now_ts + off_h * 3600 - (col_arr[-1] - col_arr) * spp
            m = (dwd_t >= t_curve[0]) & (dwd_t <= t_curve[-1])
            if m.sum() < 100:
                continue
            sc = np.interp(dwd_t[m], t_curve, val_arr)
            r = np.corrcoef(sc, dwd_s[m])[0, 1]
            if best is None or r > best[0]:
                best = (r, ppd, off_h)
    r_best, ppd, off_h = best
    print("x mapping: %.2f px/day, offset %+.1f h, r=%.3f" % (ppd, off_h, r_best))

    spp = 86400.0 / ppd
    c_last = col_arr[-1]
    t_last = now_ts + off_h * 3600

    def col_to_ts(c):
        return t_last - (c_last - c) * spp

    def sample(cols, t_center, half_min=10):
        lo = (t_center - timedelta(minutes=half_min)).timestamp()
        hi = (t_center + timedelta(minutes=half_min)).timestamp()
        vals = [y_to_ms(r) for c, r in cols.items() if lo <= col_to_ts(c) <= hi]
        return float(np.median(vals)) if vals else None

    out = []
    t = datetime(2026, 8, 14, 22, 0, tzinfo=timezone.utc)  # 15.08 00:00 CEST
    for _ in range(96):
        s = sample(mean_cols, t)
        g = sample(gust_cols, t)
        if s is not None or g is not None:
            out.append({"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "speed": None if s is None else round(max(s, 0.0), 2),
                        "gust": None if g is None else round(max(g, 0.0), 2)})
        t += timedelta(minutes=15)

    with open(os.path.join(DATA, "igb_lake_wind.json"), "w") as f:
        json.dump({"source": "IGB emon 07-ws plot scrape (speed only; "
                             "direction plot too noisy)",
                   "correlation_with_dwd": round(r_best, 3), "samples": out}, f, indent=1)

    dbg = img.copy()
    dr = ImageDraw.Draw(dbg)
    for c, rr in mean_cols.items():
        dr.point((c, rr), fill=(255, 0, 0))
    for c, rr in gust_cols.items():
        dr.point((c, rr), fill=(0, 255, 0))
    for tt in (datetime(2026, 8, 15, tzinfo=CEST), datetime(2026, 8, 16, tzinfo=CEST)):
        x = c_last - (t_last - tt.timestamp()) / spp
        dr.line([(x, 0), (x, img.height)], fill=(255, 0, 255))
    dbg.save(os.path.join(DATA, "igb_debug_ws.png"))

    print("samples:", len(out))
    for r in out:
        if "2026-08-15T05" <= r["t"] <= "2026-08-15T14":
            print(r["t"], "speed", r["speed"], "gust", r["gust"])
