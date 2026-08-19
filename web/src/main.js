import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import './style.css';
import { initGeo } from './geo.js';
import { loadTerrain } from './terrain.js';
import { loadTrack } from './track.js';
import { WindParticles } from './windParticles.js';
import { HUD } from './hud.js';

async function boot() {
  const meta = await fetch('/data/meta.json').then((r) => r.json());
  initGeo(meta.bbox);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.getElementById('app').appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x9fc7e8);
  scene.fog = new THREE.Fog(0x9fc7e8, 7000, 16000);

  const camera = new THREE.PerspectiveCamera(
    55, window.innerWidth / window.innerHeight, 1, 40000
  );
  camera.position.set(2600, 2400, 4200);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.target.set(0, 0, 0);

  // lighting: bright morning sun from the south-east + sky/ground ambient
  const hemi = new THREE.HemisphereLight(0xcfe4ff, 0x3a5f3a, 0.95);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xfff1da, 1.6);
  sun.position.set(3500, 3200, 4200);
  scene.add(sun);

  const terrain = await loadTerrain(scene, meta);
  const track = await loadTrack(scene);
  const particles = new WindParticles(scene, meta, terrain.sampleGround);
  await particles.load();

  const playback = {
    t: track.t0epoch,
    speed: 30,
    playing: true,
    follow: true,
  };
  const hud = new HUD(document.getElementById('hud'), meta, track, playback, particles);

  const endT = track.t0epoch + track.duration;
  const clock = new THREE.Clock();
  const camTargetPos = new THREE.Vector3();
  const lookTarget = new THREE.Vector3();

  function animate() {
    requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.1);
    if (playback.playing) {
      playback.t += dt * playback.speed;
      if (playback.t > endT) playback.t = track.t0epoch; // loop the day
    }

    const boat = track.update(playback.t);
    particles.update(playback.t, playback.playing ? dt * playback.speed : 0);
    hud.update(playback.t, boat);

    if (playback.follow) {
      const hRad = (boat.heading * Math.PI) / 180;
      // boat forward = (sin h, 0, -cos h); sit behind and above
      camTargetPos.set(
        boat.x - Math.sin(hRad) * 190,
        115,
        boat.z + Math.cos(hRad) * 190
      );
      camera.position.lerp(camTargetPos, 0.04);
      lookTarget.set(boat.x, 2, boat.z);
      controls.target.lerp(lookTarget, 0.08);
    }
    controls.update();
    renderer.render(scene, camera);
  }
  animate();

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // debug/verification handle
  window.__wt = { camera, controls, playback, track, particles, scene };
}

boot().catch((e) => {
  console.error(e);
  document.body.innerHTML = `<pre style="color:#fff;background:#900;padding:2em">${e.stack}</pre>`;
});
