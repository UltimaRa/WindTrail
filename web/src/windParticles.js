import * as THREE from 'three';
import { widthM, heightM } from './geo.js';
import { speedColor } from './track.js';

const N = 9000;          // particles
const HIST = 4;          // trail length (positions kept per particle)
const SEGS = N * (HIST - 1);

const VERT = /* glsl */ `
  attribute vec3 tint;
  attribute float alpha;
  varying vec3 vTint;
  varying float vAlpha;
  void main() {
    vTint = tint;
    vAlpha = alpha;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
const FRAG = /* glsl */ `
  varying vec3 vTint;
  varying float vAlpha;
  void main() { gl_FragColor = vec4(vTint, vAlpha); }
`;

export class WindParticles {
  constructor(scene, meta, sampleGround) {
    this.meta = meta;
    this.sampleGround = sampleGround;
    this.W = meta.gridW;
    this.H = meta.gridH;
    this.fieldT0 = Date.parse(meta.t0) / 1000;
    this.stepSec = meta.stepMin * 60;
    this.steps = meta.steps;

    const bbox = meta.bbox;
    this.wM = widthM();
    this.hM = heightM();
    this.cellW = this.wM / (this.W - 1);
    this.cellH = this.hM / (this.H - 1);

    // particle state
    this.px = new Float32Array(N);
    this.pz = new Float32Array(N);
    this.py = new Float32Array(N);
    this.age = new Float32Array(N);
    this.maxAge = new Float32Array(N);
    this.lowT = new Float32Array(N);
    this.spd = new Float32Array(N);
    this.hist = new Float32Array(N * HIST * 3);
    this.slot = 0;

    // geometry: line segments between consecutive history points
    this.positions = new Float32Array(SEGS * 2 * 3);
    this.tints = new Float32Array(SEGS * 2 * 3);
    this.alphas = new Float32Array(SEGS * 2);

    const geo = new THREE.BufferGeometry();
    this.posAttr = new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage);
    this.tintAttr = new THREE.BufferAttribute(this.tints, 3).setUsage(THREE.DynamicDrawUsage);
    this.alphaAttr = new THREE.BufferAttribute(this.alphas, 1).setUsage(THREE.DynamicDrawUsage);
    geo.setAttribute('position', this.posAttr);
    geo.setAttribute('tint', this.tintAttr);
    geo.setAttribute('alpha', this.alphaAttr);

    const mat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
    });
    this.lines = new THREE.LineSegments(geo, mat);
    this.lines.frustumCulled = false;
    scene.add(this.lines);

    for (let i = 0; i < N; i++) this.respawn(i, true);
  }

  async load() {
    const buf = await fetch('/data/field.bin').then((r) => r.arrayBuffer());
    this.field = new Float32Array(buf); // [step][row][col][u,v], row 0 = north
  }

  worldToGrid(x, z) {
    return [(x + this.wM / 2) / this.cellW, (z + this.hM / 2) / this.cellH];
  }

  // bilinear in space, linear in time; returns [u(east), v(north), speed]
  sampleGrid(gx, gy, fT) {
    const W = this.W, H = this.H, steps = this.steps;
    gx = Math.min(Math.max(gx, 0), W - 1.001);
    gy = Math.min(Math.max(gy, 0), H - 1.001);
    fT = Math.min(Math.max(fT, 0), steps - 1.0001);
    const x0 = Math.floor(gx), y0 = Math.floor(gy);
    const tx = gx - x0, ty = gy - y0;
    const s0 = Math.floor(fT), s1 = Math.min(s0 + 1, steps - 1);
    const ft = fT - s0;
    const F = this.field;
    const stride = W * H * 2;
    const b0 = s0 * stride + (y0 * W + x0) * 2;
    const b1 = s1 * stride + (y0 * W + x0) * 2;
    let u = 0, v = 0;
    for (let k = 0; k < 2; k++) {
      const b = k === 0 ? b0 : b1;
      const w = k === 0 ? 1 - ft : ft;
      const u00 = F[b], v00 = F[b + 1];
      const u10 = F[b + 2], v10 = F[b + 3];
      const u01 = F[b + W * 2], v01 = F[b + W * 2 + 1];
      const u11 = F[b + W * 2 + 2], v11 = F[b + W * 2 + 3];
      u += w * ((u00 * (1 - tx) + u10 * tx) * (1 - ty) + (u01 * (1 - tx) + u11 * tx) * ty);
      v += w * ((v00 * (1 - tx) + v10 * tx) * (1 - ty) + (v01 * (1 - tx) + v11 * tx) * ty);
    }
    return [u, v, Math.hypot(u, v)];
  }

  sampleWorld(x, z, tUtc) {
    const [gx, gy] = this.worldToGrid(x, z);
    return this.sampleGrid(gx, gy, (tUtc - this.fieldT0) / this.stepSec);
  }

  respawn(i, randomAge = false) {
    // 75% over the central lake region, 25% anywhere in the bbox
    const central = Math.random() < 0.75;
    const fx = central ? 0.18 + Math.random() * 0.64 : Math.random();
    const fz = central ? 0.18 + Math.random() * 0.64 : Math.random();
    const x = (fx - 0.5) * this.wM;
    const z = (fz - 0.5) * this.hM;
    const ground = Math.max(this.sampleGround(x, z), 0);
    this.px[i] = x;
    this.pz[i] = z;
    this.py[i] = ground + 2 + Math.random() * 9;
    this.age[i] = randomAge ? Math.random() * 8 : 0;
    this.maxAge[i] = 5 + Math.random() * 9;
    this.lowT[i] = 0;
    this.spd[i] = 0;
    for (let h = 0; h < HIST; h++) {
      const b = (i * HIST + h) * 3;
      this.hist[b] = x;
      this.hist[b + 1] = this.py[i];
      this.hist[b + 2] = z;
    }
  }

  update(tUtc, dtScaled) {
    if (!this.field) return;
    const fT = (tUtc - this.fieldT0) / this.stepSec;
    const n = Math.min(Math.max(Math.ceil(dtScaled / 0.2), 1), 12);
    const h = dtScaled / n;

    this.slot = (this.slot + 1) % HIST;
    const slot = this.slot;

    for (let i = 0; i < N; i++) {
      this.age[i] += dtScaled;
      let x = this.px[i], z = this.pz[i];
      let u = 0, v = 0, s = 0;
      for (let k = 0; k < n; k++) {
        const [gx, gy] = this.worldToGrid(x, z);
        const r = this.sampleGrid(gx, gy, fT + (k * h) / this.stepSec);
        u = r[0]; v = r[1]; s = r[2];
        x += u * h;
        z += -v * h; // v is northward, z is southward
      }
      this.spd[i] = s;
      if (s < 0.12) this.lowT[i] += dtScaled; else this.lowT[i] = 0;

      const [gxN, gyN] = this.worldToGrid(x, z);
      if (
        this.age[i] > this.maxAge[i] ||
        this.lowT[i] > 1.2 ||
        gxN < 0 || gxN > this.W - 1 || gyN < 0 || gyN > this.H - 1
      ) {
        this.respawn(i);
        continue;
      }
      this.px[i] = x;
      this.pz[i] = z;
      // keep height glued above ground/water
      const ground = Math.max(this.sampleGround(x, z), 0);
      const targetY = ground + 2 + ((i * 7.13) % 9);
      this.py[i] += (targetY - this.py[i]) * 0.05;

      const hb = (i * HIST + slot) * 3;
      this.hist[hb] = x;
      this.hist[hb + 1] = this.py[i];
      this.hist[hb + 2] = z;
    }

    // rebuild segment vertices from history ring buffers
    const pos = this.positions, tint = this.tints, alp = this.alphas;
    const c = [0, 0, 0];
    let vp = 0, va = 0;
    for (let i = 0; i < N; i++) {
      speedColor(this.spd[i], c);
      // whiten for contrast against water/terrain (MSFS-style bright streaks)
      c[0] = c[0] * 0.6 + 0.4;
      c[1] = c[1] * 0.6 + 0.4;
      c[2] = c[2] * 0.6 + 0.4;
      const a0 = Math.min(Math.max(this.spd[i] / 1.2, 0.3), 1);
      for (let k = 0; k < HIST - 1; k++) {
        const sA = (slot - k + HIST) % HIST;
        const sB = (slot - k - 1 + HIST) % HIST;
        const bA = (i * HIST + sA) * 3;
        const bB = (i * HIST + sB) * 3;
        pos[vp] = this.hist[bA]; pos[vp + 1] = this.hist[bA + 1]; pos[vp + 2] = this.hist[bA + 2];
        tint[vp] = c[0]; tint[vp + 1] = c[1]; tint[vp + 2] = c[2];
        vp += 3;
        pos[vp] = this.hist[bB]; pos[vp + 1] = this.hist[bB + 1]; pos[vp + 2] = this.hist[bB + 2];
        tint[vp] = c[0]; tint[vp + 1] = c[1]; tint[vp + 2] = c[2];
        vp += 3;
        const fadeHead = a0 * (1 - k / (HIST - 1));
        const fadeTail = a0 * (1 - (k + 1) / (HIST - 1));
        alp[va++] = fadeHead;
        alp[va++] = fadeTail;
      }
    }
    this.posAttr.needsUpdate = true;
    this.tintAttr.needsUpdate = true;
    this.alphaAttr.needsUpdate = true;
  }
}
