// PROTOTYPE: export a replay's falling notes as a video file, to lay over (or
// beside) a phone video of the same playing. Everything happens in the browser
// that asks for it: the Pi only serves the notes, as it does for the replay.
//
// Two looks:
//   overlay  – flat, top-down notes across all 88 keys on a solid key colour
//              (chroma green or black), so an editor can key it over camera
//              footage and stretch it to the width of the real keyboard.
//   view     – the dashboard's 3D falling notes, as a clip on its own.
//
// The recording runs in real time (canvas.captureStream + MediaRecorder), with the
// sampled piano mixed in so editors can line it up with the camera's sound.

const WHITE = (p) => ![1, 3, 6, 8, 10].includes(p % 12);

export const SIZES = { "9:16": [1080, 1920], "16:9": [1920, 1080], "1:1": [1080, 1080] };
export const BACKGROUNDS = { green: "#00b140", black: "#000000", clear: null };

// A 2D top-down piano roll drawn into `canvas`, notes landing on a line near the bottom.
export function overlayPainter(canvas, prep, { lo = 21, hi = 108, ahead = 3, background = "green", keys = true } = {}) {
  const g = canvas.getContext("2d", { alpha: background === "clear" });
  const W = canvas.width, H = canvas.height;
  const whites = []; for (let p = lo; p <= hi; p++) if (WHITE(p)) whites.push(p);
  const ww = W / whites.length, x = {};
  whites.forEach((p, i) => x[p] = i * ww);
  for (let p = lo; p <= hi; p++) if (!WHITE(p)) x[p] = x[p - 1] + ww * 0.66;
  const kh = keys ? Math.round(ww * 5.5) : 0;      // a key strip, in scale with the width
  const hit = H - kh, pps = hit / ahead;            // pixels per second of music
  const notes = prep.notes;
  const first = (t) => { let a = 0, b = notes.length; while (a < b) { const m = (a + b) >> 1; if (notes[m].on < t) a = m + 1; else b = m; } return a; };
  const col = { white: "#e57a8a", black: "#b8475b", glow: "#ffd479", line: "#d6aa52" };

  function rr(x0, y0, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    g.beginPath(); g.roundRect ? g.roundRect(x0, y0, w, h, r) : g.rect(x0, y0, w, h); g.fill();
  }

  return function draw(t) {
    const bg = BACKGROUNDS[background];
    if (bg) { g.fillStyle = bg; g.fillRect(0, 0, W, H); } else g.clearRect(0, 0, W, H);
    const down = new Map();
    for (let i = first(t - prep.maxHold), end = first(t + ahead); i < end; i++) {
      const n = notes[i];
      if (n.off <= t || n.pitch < lo || n.pitch > hi) continue;
      const w = WHITE(n.pitch), sounding = n.on <= t;
      if (sounding) down.set(n.pitch, n.vel);
      const yBottom = hit - Math.max(0, n.on - t) * pps;
      const yTop = hit - Math.min(ahead, n.off - t) * pps;
      const bw = w ? ww * 0.82 : ww * 0.56, x0 = x[n.pitch] + (w ? ww * 0.09 : 0);
      g.globalAlpha = 0.55 + 0.45 * n.vel / 127;     // louder notes are bolder
      g.fillStyle = sounding ? col.glow : (w ? col.white : col.black);
      if (sounding) { g.shadowColor = col.glow; g.shadowBlur = ww * 0.8; }
      rr(x0, yTop, bw, Math.max(4, yBottom - yTop), ww * 0.18);
      g.shadowBlur = 0; g.globalAlpha = 1;
    }
    // The line where notes sound: the top edge of the keys in the camera picture.
    g.fillStyle = col.line; g.fillRect(0, hit - 3, W, 6);
    if (!keys) return;
    for (const p of whites) {
      g.fillStyle = down.has(p) ? col.glow : "#f4efe6";
      g.fillRect(x[p] + 1, hit + 3, ww - 2, kh - 3);
    }
    for (let p = lo; p <= hi; p++) if (!WHITE(p)) {
      g.fillStyle = down.has(p) ? col.glow : "#1f1a1c";
      g.fillRect(x[p], hit + 3, ww * 0.68, kh * 0.62);
    }
  };
}

// The best container this browser records: MP4 (Safari, recent Chrome) plays on
// phones and in every editor; WebM is the fallback and the only one with alpha.
export function pickType(alpha) {
  const order = alpha ? ["video/webm;codecs=vp9", "video/webm;codecs=vp8"]
    : ["video/mp4;codecs=avc1.640028,mp4a.40.2", "video/mp4", "video/webm;codecs=vp9,opus", "video/webm"];
  return order.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
}

// Record `draw(t)` on `canvas` from `from` to `to` seconds of the replay, with the
// piano scheduled on `piano` (replay.js's sampler) into the same file.
// Resolves to a Blob. `onProgress(fraction)` while it runs.
export async function record({ canvas, draw, prep, from = 0, to = prep.duration, lead = 1.5, tail = 1.5,
                               fps = 30, piano = null, alpha = false, onProgress = () => {} }) {
  const stream = canvas.captureStream(fps);
  let dest = null;
  if (piano) {
    await piano.load();
    dest = piano.ctx.createMediaStreamDestination();
    piano.out.connect(dest);
    dest.stream.getAudioTracks().forEach((tr) => stream.addTrack(tr));
  }
  const mimeType = pickType(alpha);
  const rec = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 12e6 });
  const parts = [];
  rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
  const done = new Promise((ok) => rec.onstop = ok);

  const start = from - lead, end = to + tail;
  draw(start);
  rec.start(1000);
  const clock = piano ? () => piano.ctx.currentTime : () => performance.now() / 1000;
  const t0 = clock() + 0.1;
  if (piano) {
    for (const n of prep.notes) {
      if (n.on < from || n.on > to) continue;
      const v = piano.play(n.pitch, n.vel, t0 + (n.on - start), n.soft);
      piano.release(v, t0 + (n.sound - start));
    }
  }
  await new Promise((ok) => {
    const tick = () => {
      const t = start + Math.max(0, clock() - t0);
      draw(Math.min(t, end));
      onProgress(Math.min(1, (t - start) / (end - start)));
      if (t >= end) ok(); else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  rec.stop();
  await done;
  if (dest) piano.out.disconnect(dest);
  return new Blob(parts, { type: mimeType.split(";")[0] });
}
