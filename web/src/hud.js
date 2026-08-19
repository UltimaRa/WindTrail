import { speedColor } from './track.js';

function fmtTime(tUtc) {
  const d = new Date(tUtc * 1000);
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  const lhh = String(d.getHours()).padStart(2, '0');
  const lmm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm} UTC · ${lhh}:${lmm} local`;
}

export class HUD {
  constructor(root, meta, track, playback, particles) {
    this.track = track;
    this.playback = playback;
    this.particles = particles;
    this.meta = meta;

    root.innerHTML = `
      <div class="panel top-left">
        <div class="title">WindTrail</div>
        <div class="sub">${track.name} · Großer Müggelsee · 2026-08-15</div>
        <div class="row"><span>Time</span><b id="h-time">–</b></div>
        <div class="row"><span>Boat</span><b id="h-boat">–</b></div>
        <div class="row"><span>Wind</span><b><span id="h-wind-arrow">➤</span> <span id="h-wind">–</span></b></div>
        <div class="row"><span>Gusts</span><b id="h-gust">–</b></div>
        <div class="row"><span>Sources</span><b class="small">DWD 10-min ×${meta.blend.iconScale.toFixed(2)} · IGB lake ×${meta.blend.igbScale.toFixed(2)} · ICON-D2</b></div>
      </div>
      <div class="panel bottom">
        <button id="h-play" title="play/pause">⏸</button>
        <input id="h-scrub" type="range" min="0" max="${track.duration}" step="1" value="0" />
        <select id="h-speed">
          <option value="1">1×</option>
          <option value="5">5×</option>
          <option value="15">15×</option>
          <option value="30" selected>30×</option>
          <option value="60">60×</option>
          <option value="120">120×</option>
        </select>
        <label><input type="checkbox" id="h-follow" checked /> follow boat</label>
        <div class="legend">
          <canvas id="h-legend" width="128" height="12"></canvas>
          <div class="lab"><span>0</span><span>wind m/s</span><span>6+</span></div>
        </div>
      </div>
    `;

    this.elTime = document.getElementById('h-time');
    this.elBoat = document.getElementById('h-boat');
    this.elWind = document.getElementById('h-wind');
    this.elGust = document.getElementById('h-gust');
    this.elArrow = document.getElementById('h-wind-arrow');
    this.elPlay = document.getElementById('h-play');
    this.elScrub = document.getElementById('h-scrub');

    this.elPlay.addEventListener('click', () => {
      playback.playing = !playback.playing;
      this.elPlay.textContent = playback.playing ? '⏸' : '▶';
    });
    document.getElementById('h-speed').addEventListener('change', (e) => {
      playback.speed = parseFloat(e.target.value);
    });
    document.getElementById('h-follow').addEventListener('change', (e) => {
      playback.follow = e.target.checked;
    });
    let scrubbing = false;
    this.elScrub.addEventListener('pointerdown', () => (scrubbing = true));
    window.addEventListener('pointerup', () => (scrubbing = false));
    this.elScrub.addEventListener('input', (e) => {
      playback.t = track.t0epoch + parseFloat(e.target.value);
    });
    this.isScrubbing = () => scrubbing;

    this.drawLegend();
  }

  drawLegend() {
    const cv = document.getElementById('h-legend');
    const ctx = cv.getContext('2d');
    const c = [0, 0, 0];
    for (let x = 0; x < cv.width; x++) {
      const s = (x / (cv.width - 1)) * 6.5;
      speedColor(s, c);
      ctx.fillStyle = `rgb(${(c[0] * 255) | 0},${(c[1] * 255) | 0},${(c[2] * 255) | 0})`;
      ctx.fillRect(x, 0, 1, cv.height);
    }
  }

  update(tUtc, boat) {
    this.elTime.textContent = fmtTime(tUtc);
    const kn = boat.speed * 1.94384;
    this.elBoat.textContent = `${boat.speed.toFixed(1)} m/s (${kn.toFixed(1)} kn) · hdg ${Math.round(boat.heading)}°`;

    const [u, v, s] = this.particles.sampleWorld(boat.x, boat.z, tUtc);
    // meteorological direction: where the wind comes FROM
    const fromDir = (Math.atan2(-u, -v) * 180) / Math.PI;
    const dir = (fromDir + 360) % 360;
    const flowTo = (dir + 180) % 360;
    this.elWind.textContent = `${s.toFixed(1)} m/s from ${Math.round(dir)}°`;
    this.elArrow.style.transform = `rotate(${flowTo - 90}deg)`;
    this.elGust.textContent = `≈${(s * this.meta.gustFactor).toFixed(1)} m/s`;

    if (!this.isScrubbing()) {
      this.elScrub.value = String(Math.min(Math.max(tUtc - this.track.t0epoch, 0), this.track.duration));
    }
  }
}
