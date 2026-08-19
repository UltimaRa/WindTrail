// Headless verification screenshots for the WindTrail app.
// Usage: node e2e/shot.mjs   (dev server must be running on :5173)
import puppeteer from 'puppeteer-core';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = join(fileURLToPath(new URL('.', import.meta.url)), '..', '..', 'data', 'shots');
mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--no-sandbox', '--disable-gpu-sandbox'],
});

const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 900 });
page.on('console', (m) => {
  if (m.type() === 'error') console.log('[console.error]', m.text());
});
page.on('pageerror', (e) => console.log('[pageerror]', e.message));

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle2', timeout: 30000 });
await page.waitForFunction('window.__wt !== undefined', { timeout: 20000 });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await sleep(3500); // let particles spin up

// 1) follow-cam near trip start
await page.screenshot({ path: join(OUT, 'shot-follow.png') });
console.log('shot-follow.png');

// 2) top-down at 09:30 UTC — southerly wind, Müggelberge dead zone
await page.evaluate(() => {
  const wt = window.__wt;
  wt.playback.follow = false;
  document.getElementById('h-follow').checked = false;
  wt.playback.t = Date.parse('2026-08-15T09:30:00Z') / 1000;
  wt.camera.position.set(0, 6200, 2600);
  wt.controls.target.set(0, 0, 200);
});
await sleep(2500);
await page.screenshot({ path: join(OUT, 'shot-top-0930.png') });
console.log('shot-top-0930.png');

// 3) top-down at 12:30 UTC — westerly wind
await page.evaluate(() => {
  window.__wt.playback.t = Date.parse('2026-08-15T12:30:00Z') / 1000;
});
await sleep(2500);
await page.screenshot({ path: join(OUT, 'shot-top-1230.png') });
console.log('shot-top-1230.png');

// 4) low oblique from the SE at 10:30 UTC
await page.evaluate(() => {
  const wt = window.__wt;
  wt.playback.t = Date.parse('2026-08-15T10:30:00Z') / 1000;
  wt.camera.position.set(2600, 1400, 3600);
  wt.controls.target.set(-400, 0, -300);
});
await sleep(2500);
await page.screenshot({ path: join(OUT, 'shot-oblique-1030.png') });
console.log('shot-oblique-1030.png');

await browser.close();
console.log('done');
