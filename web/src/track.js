import * as THREE from 'three';
import { lonToX, latToZ } from './geo.js';

// speed (m/s) -> RGB, shared scale for track ribbon and wind streaks
export function speedColor(s, out) {
  let r, g, b;
  if (s < 0.5) {
    const t = s / 0.5;
    r = 0.55 + 0.1 * t; g = 0.65 + 0.12 * t; b = 0.75 + 0.1 * t;
  } else if (s < 2) {
    const t = (s - 0.5) / 1.5;
    r = 0.65 - 0.34 * t; g = 0.77 - 0.01 * t; b = 0.85 + 0.12 * t; // -> cyan
  } else if (s < 4) {
    const t = (s - 2) / 2;
    r = 0.31 + 0.69 * t; g = 0.76 + 0.16 * t; b = 0.97 - 0.74 * t; // -> yellow
  } else if (s < 6) {
    const t = (s - 4) / 2;
    r = 1.0; g = 0.92 - 0.48 * t; b = 0.23 - 0.1 * t;              // -> orange
  } else {
    r = 0.96; g = 0.30; b = 0.24;                                  // red
  }
  out[0] = r; out[1] = g; out[2] = b;
  return out;
}

function lerpAngleDeg(a, b, t) {
  const d = ((b - a + 540) % 360) - 180;
  return a + d * t;
}

function buildBoat() {
  const boat = new THREE.Group();

  const hullMat = new THREE.MeshStandardMaterial({ color: 0xf2f0ea, roughness: 0.5 });
  const hull = new THREE.Mesh(new THREE.SphereGeometry(3, 16, 10), hullMat);
  hull.scale.set(0.55, 0.28, 1.6);
  hull.position.y = 0.4;
  boat.add(hull);

  const deck = new THREE.Mesh(
    new THREE.BoxGeometry(2.2, 0.25, 6.5),
    new THREE.MeshStandardMaterial({ color: 0x8a6b46, roughness: 0.8 })
  );
  deck.position.y = 1.0;
  boat.add(deck);

  const mast = new THREE.Mesh(
    new THREE.CylinderGeometry(0.09, 0.12, 9.5, 6),
    new THREE.MeshStandardMaterial({ color: 0x555a60, roughness: 0.4 })
  );
  mast.position.set(0, 5.6, -0.4);
  boat.add(mast);

  // mainsail triangle behind the mast (stern is +z, bow faces -z)
  const sailGeo = new THREE.BufferGeometry();
  sailGeo.setAttribute(
    'position',
    new THREE.BufferAttribute(
      new Float32Array([0, 1.5, 0.0, 0, 9.6, -0.2, 0, 1.7, 4.4]), 3
    )
  );
  sailGeo.computeVertexNormals();
  const sail = new THREE.Mesh(
    sailGeo,
    new THREE.MeshStandardMaterial({
      color: 0xffffff, side: THREE.DoubleSide, roughness: 0.85,
      transparent: true, opacity: 0.96,
    })
  );
  boat.add(sail);

  return boat;
}

export async function loadTrack(scene) {
  const data = await fetch('/data/track.json').then((r) => r.json());
  const pts = data.points;
  const n = pts.length;
  const t0epoch = Date.parse(data.t0) / 1000;
  const duration = pts[n - 1].t;

  // world positions, slightly above the water plane
  const wx = new Float32Array(n);
  const wz = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    wx[i] = lonToX(pts[i].lon);
    wz[i] = latToZ(pts[i].lat);
  }

  // ---- speed-colored ribbon ----
  const HALF = 2.2;
  const positions = new Float32Array(n * 2 * 3);
  const colors = new Float32Array(n * 2 * 3);
  const c = [0, 0, 0];
  for (let i = 0; i < n; i++) {
    const iPrev = Math.max(0, i - 1);
    const iNext = Math.min(n - 1, i + 1);
    let dx = wx[iNext] - wx[iPrev];
    let dz = wz[iNext] - wz[iPrev];
    const len = Math.hypot(dx, dz) || 1;
    dx /= len; dz /= len;
    // perpendicular
    const px = -dz, pz = dx;
    const y = 1.1;
    positions[(i * 2) * 3 + 0] = wx[i] + px * HALF;
    positions[(i * 2) * 3 + 1] = y;
    positions[(i * 2) * 3 + 2] = wz[i] + pz * HALF;
    positions[(i * 2 + 1) * 3 + 0] = wx[i] - px * HALF;
    positions[(i * 2 + 1) * 3 + 1] = y;
    positions[(i * 2 + 1) * 3 + 2] = wz[i] - pz * HALF;
    speedColor(pts[i].speed, c);
    for (let k = 0; k < 2; k++) {
      colors[(i * 2 + k) * 3 + 0] = c[0];
      colors[(i * 2 + k) * 3 + 1] = c[1];
      colors[(i * 2 + k) * 3 + 2] = c[2];
    }
  }
  const idx = new Uint32Array((n - 1) * 6);
  for (let i = 0; i < n - 1; i++) {
    const a = i * 2, b = i * 2 + 1, d = i * 2 + 2, e = i * 2 + 3;
    idx.set([a, b, d, b, e, d], i * 6);
  }
  const ribGeo = new THREE.BufferGeometry();
  ribGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  ribGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  ribGeo.setIndex(new THREE.BufferAttribute(idx, 1));
  const ribbon = new THREE.Mesh(
    ribGeo,
    new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide })
  );
  scene.add(ribbon);

  // start / finish markers
  const markerGeo = new THREE.ConeGeometry(4, 14, 8);
  const startM = new THREE.Mesh(markerGeo, new THREE.MeshStandardMaterial({ color: 0x35d07f }));
  startM.position.set(wx[0], 8, wz[0]);
  scene.add(startM);
  const endM = new THREE.Mesh(markerGeo, new THREE.MeshStandardMaterial({ color: 0xe04848 }));
  endM.position.set(wx[n - 1], 8, wz[n - 1]);
  scene.add(endM);

  // ---- boat ----
  const boat = buildBoat();
  scene.add(boat);

  const times = new Float32Array(n);
  for (let i = 0; i < n; i++) times[i] = pts[i].t;

  function update(tUtc) {
    const t = Math.min(Math.max(tUtc - t0epoch, 0), duration);
    // binary search
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (times[mid] <= t) lo = mid; else hi = mid;
    }
    const span = times[hi] - times[lo] || 1;
    const f = (t - times[lo]) / span;
    const x = wx[lo] + (wx[hi] - wx[lo]) * f;
    const z = wz[lo] + (wz[hi] - wz[lo]) * f;
    const heading = lerpAngleDeg(pts[lo].heading, pts[hi].heading, f);
    const speed = pts[lo].speed + (pts[hi].speed - pts[lo].speed) * f;

    boat.position.set(x, 0.4, z);
    boat.rotation.y = (-heading * Math.PI) / 180;
    return { x, z, heading, speed, t };
  }

  return { update, t0epoch, duration, name: data.name, stats: data.stats };
}
