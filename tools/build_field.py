"""Build the terrain-aware wind field -> web/public/data/field.bin + meta.json

Background wind (10-min steps, 05:00-14:00 UTC):
  inverse-distance blend of DWD 00427/00433, bias-corrected by ICON-D2 at the
  lake, scaled to the scraped IGB on-lake speed curve.

Terrain perturbation per time step on a 120x120 grid:
  - orographic speed-up on windward slopes (slope-based, capped +35%)
  - lee wind-shadow behind barriers: deficit ~ exp(-d / (12*H)), the
    Mueggelberge dead-zone for southerly winds
  - deflection: flow rotated toward contour-parallel near high barriers
  - roughness: +12% over open water
  - channeling along the lake's long axis (ENE-WSW) for near-axis flow

Outputs field.bin (Float32 [T][120][120][2] u/v m/s), meta.json, a validation
chart (sources vs final lake estimate) and quiver maps for two time steps.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "web", "public", "data")

LAKE = {"lat": 52.4376, "lon": 13.6567}
T0 = datetime(2026, 8, 15, 5, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 15, 14, 0, tzinfo=timezone.utc)
STEP_MIN = 10

FG = 120          # field grid size
FETCH_M = 2200    # upwind scan distance for barrier detection
LAKE_AXIS_DEG = 75.0  # long axis of Grosser Mueggelsee (approx ENE-WSW)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def dirspeed_to_uv(direction_deg, speed):
    """meteorological direction (from) -> u (east), v (north) components"""
    th = np.radians(direction_deg)
    return -speed * np.sin(th), -speed * np.cos(th)


def uv_to_dirspeed(u, v):
    speed = np.hypot(u, v)
    direction = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
    return direction, speed


def parse_dwd_time(s):
    return datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


def interp_series(times, values, t_query):
    ts = np.array([t.timestamp() for t in times])
    return float(np.interp(t_query.timestamp(), ts, values))


def main():
    obs = json.load(open(os.path.join(DATA, "wind_obs.json")))
    igb = json.load(open(os.path.join(DATA, "igb_lake_wind.json")))["samples"]
    geo = json.load(open(os.path.join(DATA, "geo.json")))
    bbox = geo["bbox"]
    terrain = np.fromfile(os.path.join(DATA, "terrain.bin"), dtype=np.float32)
    terrain = terrain.reshape(geo["grid"], geo["grid"])

    # ---- time base ----
    n_steps = int((T1 - T0).total_seconds() // (STEP_MIN * 60)) + 1
    times = [T0 + timedelta(minutes=STEP_MIN * i) for i in range(n_steps)]

    # ---- DWD series -> u/v per station ----
    dwd = {}
    for sid, st in obs["dwd"].items():
        ts = [parse_dwd_time(r["t"]) for r in st["series"]]
        u, v = dirspeed_to_uv(np.array([r["dir"] for r in st["series"]]),
                              np.array([r["speed"] for r in st["series"]]))
        dwd[sid] = {"lat": st["lat"], "lon": st["lon"], "ts": ts, "u": u, "v": v}

    dists = {sid: haversine_m(LAKE["lat"], LAKE["lon"], st["lat"], st["lon"])
             for sid, st in dwd.items()}
    w = {sid: 1.0 / d ** 2 for sid, d in dists.items()}
    wsum = sum(w.values())

    # ---- ICON-D2 hourly at 3 lake points ----
    om = obs["openmeteo"]
    om_ts = [datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
             for t in om[0]["time"]]
    om_u = np.mean([dirspeed_to_uv(np.array(p["dir"]), np.array(p["speed"]))[0] for p in om], axis=0)
    om_v = np.mean([dirspeed_to_uv(np.array(p["dir"]), np.array(p["speed"]))[1] for p in om], axis=0)

    # ---- per-step background ----
    bg_u, bg_v = np.zeros(n_steps), np.zeros(n_steps)
    dwd_spd_all, om_spd_all = [], []
    for i, t in enumerate(times):
        u_d = sum(w[sid] * interp_series(dwd[sid]["ts"], dwd[sid]["u"], t)
                  for sid in dwd) / wsum
        v_d = sum(w[sid] * interp_series(dwd[sid]["ts"], dwd[sid]["v"], t)
                  for sid in dwd) / wsum
        u_m = interp_series(om_ts, om_u, t)
        v_m = interp_series(om_ts, om_v, t)
        dwd_spd_all.append(np.hypot(u_d, v_d))
        om_spd_all.append(np.hypot(u_m, v_m))
        bg_u[i] = 0.5 * u_d + 0.5 * u_m
        bg_v[i] = 0.5 * v_d + 0.5 * v_m

    # bias-correct: scale the DWD/ICON blend toward ICON's lake-level speeds
    scale = float(np.clip(np.mean(om_spd_all) / max(np.mean(dwd_spd_all), 0.1), 0.8, 1.3))
    bg_u *= scale
    bg_v *= scale

    # ---- IGB on-lake speed calibration ----
    igb_rows = [r for r in igb if r["speed"] is not None]
    igb_t = [datetime.strptime(r["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
             for r in igb_rows]
    igb_s = [r["speed"] for r in igb_rows]
    bg_at_igb = [np.hypot(interp_series(times, bg_u, t), interp_series(times, bg_v, t))
                 for t in igb_t]
    igb_scale = float(np.clip(np.mean(igb_s) / max(np.mean(bg_at_igb), 0.1), 0.7, 1.6))
    bg_u *= igb_scale
    bg_v *= igb_scale
    gust_pairs = [(r["gust"], r["speed"]) for r in igb_rows
                  if r["gust"] is not None and r["speed"] > 0.3]
    gust_factor = float(np.mean([g / s for g, s in gust_pairs])) if gust_pairs else 1.4
    print("blend: ICON/DWD speed scale %.2f, IGB lake scale %.2f, gust factor %.2f"
          % (scale, igb_scale, gust_factor))

    # ---- grid setup ----
    terr = np.asarray(Image.fromarray(terrain, mode="F").resize((FG, FG), Image.BILINEAR),
                      dtype=np.float32)
    H, W = terr.shape
    lat0, lat1 = bbox["minLat"], bbox["maxLat"]
    lon0, lon1 = bbox["minLon"], bbox["maxLon"]
    cell_ns = haversine_m(lat0, lon0, lat1, lon0) / (H - 1)   # meters per cell N-S
    cell_we = haversine_m(lat0, lon0, lat0, lon1) / (W - 1)   # meters per cell W-E
    water = terr < 33.8

    # smoothed terrain for slopes (simple 5x5 box blur twice)
    def smooth(z):
        for _ in range(2):
            z = (np.roll(z, 1, 0) + np.roll(z, -1, 0) + np.roll(z, 1, 1)
                 + np.roll(z, -1, 1) + z * 2) / 6.0
        return z
    terr_s = smooth(terr)

    # ---- per-step perturbation ----
    field = np.zeros((n_steps, H, W, 2), dtype=np.float32)
    n_scan = 24
    for i, t in enumerate(times):
        u0, v0 = bg_u[i], bg_v[i]
        spd0 = max(np.hypot(u0, v0), 0.1)
        # unit vector of flow direction (where wind goes TO)
        fx, fy = u0 / spd0, v0 / spd0
        # upwind scan: barrier height above each cell + distance to crest
        barrier = np.zeros((H, W), dtype=np.float32)
        crest_dist = np.full((H, W), FETCH_M, dtype=np.float32)
        for k in range(3, n_scan):
            d = k / n_scan * FETCH_M
            dy = int(round(k / n_scan * FETCH_M / cell_ns * fy))
            dx = int(round(k / n_scan * FETCH_M / cell_we * fx))
            z_up = np.roll(terr_s, (-dy, -dx), axis=(0, 1))  # terrain upwind
            excess = z_up - terr_s
            better = excess > barrier
            barrier = np.where(better, excess, barrier)
            crest_dist = np.where(better, d, crest_dist)

        # lee shadow: deficit decays with distance from crest
        H_b = np.clip(barrier, 0, None)
        deficit = np.where(H_b > 8.0,
                           np.minimum(0.65, 0.022 * H_b)
                           * np.exp(-crest_dist / (12.0 * np.maximum(H_b, 10.0))),
                           0.0)
        deficit = np.clip(deficit, 0, 0.7)

        # orographic speed-up: slope along flow over ~2 cells
        dy2 = int(round(2 * fy)) or (1 if fy > 0 else -1)
        dx2 = int(round(2 * fx)) or (1 if fx > 0 else -1)
        z_up2 = np.roll(terr_s, (-dy2, -dx2), axis=(0, 1))
        dist2 = np.hypot(dy2 * cell_ns, dx2 * cell_we)
        # windward slope rises against the flow: z here higher than upwind
        slope_along = (terr_s - z_up2) / dist2  # >0 on windward-facing slope
        speedup = 1.0 + np.clip(1.8 * slope_along, 0.0, 0.35)

        # deflection around high barriers: rotate toward contour-parallel
        gy, gx = np.gradient(terr_s, cell_ns, cell_we)
        gm = np.hypot(gx, gy) + 1e-6
        # contour-parallel unit vector (perpendicular to gradient)
        tx, ty = -gy / gm, gx / gm
        # choose sign so that it aligns with flow
        dot = tx * fx + ty * fy
        tx = np.where(dot < 0, -tx, tx)
        ty = np.where(dot < 0, -ty, ty)
        w_defl = np.clip(H_b / 160.0, 0, 0.45)
        u_d = (1 - w_defl) * fx + w_defl * tx
        v_d = (1 - w_defl) * fy + w_defl * ty
        nm = np.hypot(u_d, v_d) + 1e-6
        u_d, v_d = u_d / nm, v_d / nm

        # roughness: open water faster
        rough = np.where(water, 1.12, 1.0)

        # channeling along lake axis over water
        axis_th = np.radians(LAKE_AXIS_DEG)
        ax, ay = np.sin(axis_th), np.cos(axis_th)  # unit along axis
        dot_ax = fx * ax + fy * ay
        ang = np.degrees(np.arccos(np.clip(abs(dot_ax), 0, 1)))
        chan_w = np.clip((30.0 - ang) / 30.0, 0, 1) * 0.35
        ax_s = np.where(dot_ax < 0, -ax, ax)
        ay_s = np.where(dot_ax < 0, -ay, ay)
        u_c = (1 - chan_w) * u_d + chan_w * ax_s
        v_c = (1 - chan_w) * v_d + chan_w * ay_s
        nm = np.hypot(u_c, v_c) + 1e-6
        u_c, v_c = u_c / nm, v_c / nm
        chan_boost = np.where(water, 1.0 + 0.12 * (chan_w / 0.35), 1.0)

        spd = spd0 * speedup * (1.0 - deficit) * rough * chan_boost
        field[i, :, :, 0] = u_c * spd
        field[i, :, :, 1] = v_c * spd

    os.makedirs(OUT, exist_ok=True)
    field.astype("<f4").tofile(os.path.join(OUT, "field.bin"))

    meta = {
        "bbox": bbox,
        "gridW": W,
        "gridH": H,
        "t0": times[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stepMin": STEP_MIN,
        "steps": n_steps,
        "lakeLevel": 33.8,
        "gustFactor": round(gust_factor, 3),
        "blend": {"iconScale": round(scale, 3), "igbScale": round(igb_scale, 3)},
        "background": [
            {"t": times[i].strftime("%Y-%m-%dT%H:%M:%SZ"),
             "dir": round(float(uv_to_dirspeed(bg_u[i], bg_v[i])[0]), 1),
             "speed": round(float(np.hypot(bg_u[i], bg_v[i])), 2)}
            for i in range(n_steps)
        ],
    }
    with open(os.path.join(OUT, "meta.json"), "w") as f:
        json.dump(meta, f)
    print("wrote field.bin %.1f MB, meta.json"
          % (os.path.getsize(os.path.join(OUT, "field.bin")) / 1e6))

    validation_chart(times, dwd, om_ts, om_u, om_v, igb_t, igb_s, bg_u, bg_v)
    quiver_maps(terr, water, field, times, bbox)


def validation_chart(times, dwd, om_ts, om_u, om_v, igb_t, igb_s, bg_u, bg_v):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    colors = {"00427": "tab:blue", "00433": "tab:cyan"}
    for sid, st in dwd.items():
        axes[0].plot(st["ts"], np.hypot(st["u"], st["v"]), ".", ms=3,
                     color=colors.get(sid, "gray"), label="DWD %s" % sid, alpha=0.6)
        axes[1].plot(st["ts"], (np.degrees(np.arctan2(-st["u"], -st["v"])) + 360) % 360,
                     ".", ms=3, color=colors.get(sid, "gray"), alpha=0.6)
    om_spd = np.hypot(om_u, om_v)
    om_dir = (np.degrees(np.arctan2(-om_u, -om_v)) + 360) % 360
    axes[0].plot(om_ts, om_spd, "s-", color="tab:green", label="ICON-D2 lake", lw=1)
    axes[1].plot(om_ts, om_dir, "s-", color="tab:green", lw=1)
    axes[0].plot(igb_t, igb_s, "o", color="tab:red", ms=4, label="IGB lake (scraped)")
    bg_spd = np.hypot(bg_u, bg_v)
    bg_dir = (np.degrees(np.arctan2(-bg_u, -bg_v)) + 360) % 360
    axes[0].plot(times, bg_spd, "-", color="black", lw=2, label="final background")
    axes[1].plot(times, bg_dir, "-", color="black", lw=2)
    axes[0].set_ylabel("wind speed [m/s]")
    axes[1].set_ylabel("direction [deg]")
    axes[0].legend(loc="upper left", fontsize=8)
    axes[0].grid(alpha=0.3)
    axes[1].grid(alpha=0.3)
    axes[1].set_ylim(0, 360)
    fig.suptitle("Wind source blend for 2026-08-15 (UTC)")
    fig.tight_layout()
    fig.savefig(os.path.join(DATA, "field_validation.png"), dpi=110)
    print("wrote field_validation.png")


def quiver_maps(terr, water, field, times, bbox):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # pick a southerly step and a westerly step
    idxs = []
    for i in range(len(times)):
        d, s = uv_to_dirspeed(field[i, :, :, 0].mean(), field[i, :, :, 1].mean())
        if 150 < d < 210 and not idxs:
            idxs.append(i)
    idxs.append(len(times) - 1)
    fig, axes = plt.subplots(1, len(idxs), figsize=(14, 6))
    if len(idxs) == 1:
        axes = [axes]
    for ax, i in zip(axes, idxs):
        terr_rgb = np.zeros((*terr.shape, 3))
        h = np.clip((terr - 30) / 85.0, 0, 1)
        terr_rgb[..., 0] = 0.35 + h * 0.6
        terr_rgb[..., 1] = 0.55 - h * 0.15
        terr_rgb[..., 2] = 0.35 + h * 0.1
        terr_rgb[water] = (0.25, 0.5, 0.75)
        ax.imshow(terr_rgb, origin="upper")
        spd = np.hypot(field[i, :, :, 0], field[i, :, :, 1])
        q = 6
        Y, X = np.mgrid[0:terr.shape[0]:q, 0:terr.shape[1]:q]
        ax.quiver(X, Y, field[i, ::q, ::q, 0], -field[i, ::q, ::q, 1],
                  spd[::q, ::q], cmap="coolwarm", scale=120)
        d, s = uv_to_dirspeed(field[i].reshape(-1, 2).mean(axis=0)[0],
                              field[i].reshape(-1, 2).mean(axis=0)[1])
        ax.set_title("%s UTC  bg %.0f deg" % (times[i].strftime("%H:%M"), d), fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("Wind field over terrain (color = speed)")
    fig.tight_layout()
    fig.savefig(os.path.join(DATA, "field_quiver.png"), dpi=110)
    print("wrote field_quiver.png")


if __name__ == "__main__":
    main()
