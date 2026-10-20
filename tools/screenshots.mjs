// Regenerates the README screenshots in docs/ from a running dashboard.
//
//   python3 -m pianotrack --db /tmp/demo.db backfill --days 120 --seed 3
//   python3 -m pianotrack --db /tmp/demo.db run --no-collector --port 8099 &
//   npm install --no-save playwright && node tools/screenshots.mjs http://localhost:8099
//
// Pass a Chromium path as the second argument if Playwright's own browser is not installed.
import { chromium } from "playwright";

const base = process.argv[2] || "http://localhost:8099";
const executablePath = process.argv[3] || process.env.CHROMIUM_PATH || undefined;
const out = new URL("../docs/", import.meta.url).pathname;

const browser = await chromium.launch({ executablePath, args: ["--autoplay-policy=no-user-gesture-required"] });
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

// Main dashboard, light, desktop: everything above the session list.
let page = await open(1100, "light");
await page.screenshot({ path: out + "dashboard.png", fullPage: true, clip: await page.evaluate(() => {
  const r = document.querySelector("#all-keys").closest("section").getBoundingClientRect();
  return { x: 0, y: 0, width: 1100, height: r.bottom + window.scrollY + 16 };
}) });
await (await card(page, "#all-keys")).screenshot({ path: out + "keys.png" });

// Session detail with replay mid-playback.
await page.click("#sessions tr:nth-child(2)");
await page.waitForTimeout(600);
await page.click(".rp-play");
await page.waitForFunction(() => document.querySelectorAll(".rp-k.on").length > 0, null, { timeout: 15000 });
await page.waitForTimeout(400);
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
