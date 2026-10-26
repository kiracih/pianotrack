// Regenerates the README screenshots in docs/ from a running dashboard.
//
//   python3 -m pianotrack --db /tmp/demo.db backfill --days 120 --seed 3 --beginner
//   python3 -m pianotrack --db /tmp/demo.db run --no-collector --port 8099 &
//   npm install --no-save playwright && node tools/screenshots.mjs http://localhost:8099
//
// Pass a Chromium path as the second argument if Playwright's own browser is not installed.
import { chromium } from "playwright";
import { existsSync, writeFileSync } from "node:fs";

const base = process.argv[2] || "http://localhost:8099";
const executablePath = process.argv[3] || process.env.CHROMIUM_PATH || undefined;
const out = new URL("../docs/", import.meta.url).pathname;

const browser = await chromium.launch({ executablePath, args: ["--autoplay-policy=no-user-gesture-required", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const errors = [];

async function open(width, scheme) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: scheme, deviceScaleFactor: 2 });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base + "/");
  await page.waitForSelector("#sessions tr");
  await page.waitForTimeout(800);
  return page;
}
const card = (page, sel) => page.$(sel).then((h) => h.evaluateHandle((e) => e.closest("section")));

// Name some of the simulator's pieces the way the owner would, by ear (here by their
// most played phrase). One stays unnamed to show how that looks.
const known = { "Für Elise": [76, 75, 76, 71, 74, 72], "Minuet in G": [67, 69, 71, 72, 74, 67],
  "Twinkle": [79, 77, 77, 76, 76, 74] };
const req = (await browser.newContext()).request;
for (const p of await (await req.get(base + "/api/pieces")).json()) {
  if (p.name || !Object.keys(known).length) continue;
  const [name, hits] = Object.entries(known).map(([n, o]) => [n, o.filter((v, i) => p.opening.notes[i] === v).length])
    .sort((a, b) => b[1] - a[1])[0];
  if (hits >= 5) { await req.post(base + "/api/pieces/name", { data: { key: p.key, name } }); delete known[name]; }
}

// Main dashboard, light, desktop: everything above the session list.
let page = await open(1100, "light");
// The 3D key map loads when its card scrolls into view; let the columns finish rising.
await page.locator("#all-keys").scrollIntoViewIfNeeded();
await page.waitForSelector("#keys-3d-note:not([hidden])", { timeout: 15000 });
await page.waitForTimeout(2500);
await page.evaluate(() => window.scrollTo(0, 0));
await page.screenshot({ path: out + "dashboard.png", fullPage: true, clip: await page.evaluate(() => {
  const r = document.querySelector("#all-keys").closest("section").getBoundingClientRect();
  return { x: 0, y: 0, width: 1100, height: r.bottom + window.scrollY + 16 };
}) });
await (await card(page, "#all-keys")).screenshot({ path: out + "keys.png" });

// Pieces, with the most played one opened to its per-session charts.
await page.click("#pieces tr[data-key]");
await page.waitForSelector("#pc-tempo svg");
await (await page.$("#pieces-card")).screenshot({ path: out + "pieces.png" });
await page.click("#pieces tr[data-key]");

// Backup box after a fresh backup. For the demo, pretend a Mac has pulled a copy
// (deploy/mac/pull-backup.sh leaves this mark on the Pi).
await page.click("#bk-now");
await page.waitForFunction(() => document.querySelector("#bk-msg").textContent === "Done");
const bk = await (await page.request.get(base + "/api/backups")).json();
if (existsSync(bk.dir) && !bk.offsite) writeFileSync(bk.dir + "/offsite", `halils-mac ${bk.files[0].name}\n`);
await page.evaluate(() => showBackup());
await page.waitForFunction(() => document.querySelector("#bk-status").textContent.includes("copied"));
await page.evaluate(() => { document.querySelector("#bk-msg").textContent = ""; });
await (await page.$("#backup-box")).screenshot({ path: out + "backup.png" });

// Session detail with replay mid-playback.
await page.click("#sessions tr:nth-child(2)");
await page.waitForTimeout(600);
await page.click(".rp-play");
// Playing for a few seconds puts falling notes on the keys (or lights the flat keyboard).
await page.waitForFunction(() => /^0:0[3-9]/.test(document.querySelector(".rp-time").textContent), null, { timeout: 20000 });
await page.click(".rp-play");
await (await page.$("#replay")).screenshot({ path: out + "replay.png" });
await (await page.$("#detail-card")).screenshot({ path: out + "session.png" });
await page.close();

// Phone, dark.
page = await open(390, "dark");
await page.screenshot({ path: out + "phone.png", fullPage: true, clip: { x: 0, y: 0, width: 390, height: 1500 } });
await page.close();

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("screenshots written to", out);
