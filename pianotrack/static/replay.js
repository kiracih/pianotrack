// Session replay: a Web Audio piano sampler plus a keyboard that lights up.
//
// Samples are the Salamander Grand Piano (CC-BY 3.0), one every minor third,
// served by the Pi itself so replay works without internet access.

(() => {
const SAMPLE_NAMES = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"];
const LOWEST = 21, HIGHEST = 108;
const PAUSE_LIMIT = 3.0;   // "skip pauses" squeezes silences longer than this...
const PAUSE_KEEP = 1.5;    // ...down to this
const LOOKAHEAD = 0.25;    // seconds of audio scheduled ahead

class PianoSampler {
  constructor() {
    this.ctx = null;
    this.buffers = {};
    this.loading = null;
  }

  unlock() {
    // Must run synchronously inside the click: Safari only starts audio from a user gesture.
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      this.out = this.ctx.createGain();
      this.out.gain.value = 0.8;
      const comp = this.ctx.createDynamicsCompressor();
      this.out.connect(comp).connect(this.ctx.destination);
    }
    if (this.ctx.state !== "running") this.ctx.resume();
  }

  load() {
    if (this.loading) return this.loading;
    this.unlock();
    const jobs = [];
    for (let p = LOWEST; p <= HIGHEST; p += 3) {
      const name = SAMPLE_NAMES[p % 12] + (Math.floor(p / 12) - 1);
      jobs.push(fetch(`/piano/${name}.mp3`, { credentials: "same-origin" })
        .then((r) => {
          // Behind a login wall an expired session returns an HTML sign-in page instead.
          const type = r.headers.get("content-type") || "";
          if (!r.ok || !type.startsWith("audio/")) throw new Error(`piano sample ${name}: HTTP ${r.status} ${type}`);
          return r.arrayBuffer();
        })
        .then((b) => new Promise((ok, bad) => this.ctx.decodeAudioData(b, ok, bad)))
        .then((buf) => { this.buffers[p] = buf; }));
    }
    this.loading = Promise.all(jobs).catch((e) => { this.loading = null; throw e; });
    return this.loading;
  }

  play(pitch, velocity, when, soft) {
    const base = Math.min(HIGHEST, LOWEST + 3 * Math.round((pitch - LOWEST) / 3));
    const buf = this.buffers[base];
    if (!buf) return null;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = Math.pow(2, (pitch - base) / 12);
    const v = velocity / 127;
    // Softer notes are quieter and darker, like hammers on real strings.
    const tone = this.ctx.createBiquadFilter();
    tone.type = "lowpass";
    tone.frequency.value = 900 + 11000 * v * v * (soft ? 0.6 : 1);
    const gain = this.ctx.createGain();
    gain.gain.value = Math.pow(v, 1.6) * (soft ? 0.7 : 1);
    src.connect(tone).connect(gain).connect(this.out);
    src.start(Math.max(when, this.ctx.currentTime));
    return { src, gain };
  }

  release(voice, when) {
    if (!voice) return;
    const t = Math.max(when, this.ctx.currentTime);
    voice.gain.gain.setTargetAtTime(0, t, 0.09);
    try { voice.src.stop(t + 1.2); } catch (e) { /* already stopped */ }
  }

  silence() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.out.gain.setTargetAtTime(0, t, 0.02);
    this.out.gain.setTargetAtTime(0.8, t + 0.15, 0.01);
  }
}

// Prepare raw events: work out when each note actually stops sounding
// (held by the sustain pedal), whether the soft pedal was down, and an
// optional time warp that shortens long pauses.
function prepare(data, skipPauses) {
  const notes = data.notes.slice().sort((a, b) => a[0] - b[0]);
  const pedals = data.pedals.slice().sort((a, b) => a[0] - b[0]);

  const intervals = (cc) => {
    const out = []; let down = null;
    for (const [t, c, v] of pedals) {
      if (c !== cc) continue;
      if (v >= 64 && down === null) down = t;
      else if (v < 64 && down !== null) { out.push([down, t]); down = null; }
    }
    if (down !== null) out.push([down, Infinity]);
    return out;
  };
  const sustain = intervals(64), soft = intervals(67);
  const within = (iv, t) => iv.find(([a, b]) => a <= t && t < b);

  // Time warp breakpoints: [realTime, shiftSoFar]
  const warp = [[0, 0]];
  if (skipPauses) {
    let shift = 0, busyUntil = notes.length ? notes[0][0] : 0;
    for (const n of notes) {
      const gap = n[0] - busyUntil;
      if (gap > PAUSE_LIMIT) {
        shift += gap - PAUSE_KEEP;
        warp.push([n[0], shift]);
      }
      busyUntil = Math.max(busyUntil, n[1]);
    }
  }
  const map = (t) => {
    let lo = 0, hi = warp.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (warp[mid][0] <= t) lo = mid; else hi = mid - 1; }
    return t - warp[lo][1];
  };

  const out = notes.map(([on, off, pitch, vel]) => {
    const held = within(sustain, off);
    const sound = held ? Math.min(held[1], off + 12) : off;
    return { on: map(on), off: map(off), sound: map(Math.max(off, sound)) + 0.05,
             pitch, vel, soft: !!within(soft, on) };
  });
  const pedalTimeline = sustain.map(([a, b]) => [map(a), b === Infinity ? Infinity : map(b)]);
  const duration = Math.max(0, ...out.map((n) => n.sound));
  let maxHold = 0; for (const n of out) maxHold = Math.max(maxHold, n.off - n.on);
  return { notes: out, sustain: pedalTimeline, duration, maxHold, skipped: warp.length - 1, map };
}

const piano = new PianoSampler();

class Replay {
  constructor(root) {
    this.root = root;
    this.data = null;
    this.prep = null;
    this.playing = false;
    this.pos = 0;
    this.speed = 1;
    this.skip = true;
    this.voices = [];
    this.timer = null;
    this.raf = null;
    this.build();
  }

  build() {
    const r = this.root;
    r.innerHTML = `
      <div class="rp-bar">
        <button class="rp-play" aria-label="Play">▶</button>
        <span class="rp-time">0:00 / 0:00</span>
        <input class="rp-seek" type="range" min="0" max="1000" value="0" aria-label="Seek">
        <select class="rp-speed" aria-label="Speed">
          <option value="0.5">0.5×</option><option value="0.75">0.75×</option>
          <option value="1" selected>1×</option><option value="1.5">1.5×</option><option value="2">2×</option>
        </select>
        <label class="rp-skip"><input type="checkbox" checked> Skip pauses</label>
        <label class="rp-skip rp-fall" hidden><input type="checkbox"> Falling notes</label>
      </div>
      <div class="rp-3d" hidden></div>
      <div class="rp-kbd"></div>
      <div class="rp-status"><span class="rp-sus">Sustain</span><span class="rp-soft">Soft</span><span class="rp-msg"></span></div>`;
    this.$ = (sel) => r.querySelector(sel);
    this.$(".rp-play").onclick = () => (this.playing ? this.pause() : this.play());
    this.$(".rp-seek").oninput = (e) => this.seek(e.target.value / 1000 * (this.prep ? this.prep.duration : 0));
    this.$(".rp-speed").onchange = (e) => { const was = this.playing; this.pause(); this.speed = +e.target.value; if (was) this.play(); };
    this.$(".rp-skip input").onchange = (e) => {
      const frac = this.prep ? this.pos / this.prep.duration : 0;
      const was = this.playing; this.pause();
      this.skip = e.target.checked; this.prep = prepare(this.data, this.skip);
      if (this.view) this.view.setNotes(this.prep, (t) => this.firstIndexFrom(t));
      this.pos = frac * this.prep.duration; this.draw(); if (was) this.play();
    };
    this.drawKeyboard();
  }

  // An optional 3D view (falling3d.js) that follows the player. "Falling notes"
  // swaps it with the flat keyboard; the choice is remembered on this device.
  attachView(view) {
    this.view = view;
    const box = this.$(".rp-fall input");
    let on = true;
    try { on = localStorage.getItem("pianotrack.falling") !== "off"; } catch (e) { /* private mode */ }
    box.checked = on;
    this.$(".rp-fall").hidden = false;
    const show = () => {
      this.$(".rp-3d").hidden = !box.checked;
      this.$(".rp-kbd").hidden = box.checked;
      if (this.prep) this.view.setNotes(this.prep, (t) => this.firstIndexFrom(t));
      this.draw();
    };
    box.onchange = () => {
      try { localStorage.setItem("pianotrack.falling", box.checked ? "on" : "off"); } catch (e) { /* private mode */ }
      show();
    };
    show();
  }

  drawKeyboard() {
    const NS = "http://www.w3.org/2000/svg";
    const isBlack = (p) => [1, 3, 6, 8, 10].includes(p % 12);
    const ww = 12, H = 80, bh = 50;
    const whites = []; for (let p = LOWEST; p <= HIGHEST; p++) if (!isBlack(p)) whites.push(p);
    const W = whites.length * ww;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", "100%");
    svg.style.minWidth = `${W * 0.7}px`;
    this.keys = {};
    const pos = {};
    whites.forEach((p, i) => { pos[p] = i * ww; });
    const mk = (p, x, w, h, black) => {
      const k = document.createElementNS(NS, "rect");
      Object.entries({ x, y: 0, width: w, height: h, rx: black ? 1.5 : 2 }).forEach(([a, v]) => k.setAttribute(a, v));
      k.setAttribute("class", black ? "rp-k rp-b" : "rp-k rp-w");
      svg.appendChild(k);
      this.keys[p] = k;
    };
    for (const p of whites) mk(p, pos[p] + 0.5, ww - 1, H, false);
    for (let p = LOWEST + 1; p <= HIGHEST; p++) if (isBlack(p)) mk(p, pos[p - 1] + ww - 4, 8, bh, true);
    this.$(".rp-kbd").appendChild(svg);
  }

  load(id) {
    if (this.id === id) return this.loading;
    this.loading = this._load(id);
    return this.loading;
  }

  async _load(id) {
    this.stop();
    this.id = id;
    this.$(".rp-msg").textContent = "";
    const r = await fetch(`/api/sessions/${id}/events`);
    if (!r.ok || this.id !== id) return;
    this.data = await r.json();
    this.prep = prepare(this.data, this.skip);
    if (this.view) this.view.setNotes(this.prep, (t) => this.firstIndexFrom(t));
    this.pos = 0;
    this.draw();
  }

  // Load a session and move to `t` seconds after its start (real time, before pause skipping).
  async jump(id, t) {
    await this.load(id);
    if (this.id !== id || !this.prep) return;
    this.seek(this.prep.map(t));
  }

  async play() {
    if (!this.prep || !this.prep.notes.length) return;
    piano.unlock();
    if (Object.keys(piano.buffers).length < 30) {
      this.$(".rp-msg").textContent = "Loading piano…";
      try { await piano.load(); } catch (e) {
        console.error(e);
        this.$(".rp-msg").textContent = "Could not load the piano sound. Reload the page and try again.";
        return;
      }
      this.$(".rp-msg").textContent = "";
    }
    await piano.ctx.resume();
    if (this.pos >= this.prep.duration - 0.05) this.pos = 0;
    this.playing = true;
    this.$(".rp-play").textContent = "❚❚";
    this.$(".rp-play").setAttribute("aria-label", "Pause");
    this.ctxStart = piano.ctx.currentTime + 0.05;
    this.posStart = this.pos;
    this.next = this.firstIndexFrom(this.pos);
    this.timer = setInterval(() => this.schedule(), 50);
    this.schedule();
    const tick = () => { if (!this.playing) return; this.pos = this.now(); this.draw(); this.raf = requestAnimationFrame(tick); };
    this.raf = requestAnimationFrame(tick);
  }

  pause() {
    if (!this.playing) return;
    this.pos = this.now();
    this.halt();
    this.draw();
  }

  stop() { this.halt(); this.pos = 0; this.draw(); }

  halt() {
    this.playing = false;
    clearInterval(this.timer); cancelAnimationFrame(this.raf);
    piano.silence();
    for (const v of this.voices) piano.release(v.voice, 0);
    this.voices = [];
    if (this.$) { this.$(".rp-play").textContent = "▶"; this.$(".rp-play").setAttribute("aria-label", "Play"); }
  }

  seek(t) {
    const was = this.playing;
    this.halt();
    this.pos = Math.max(0, Math.min(t, this.prep ? this.prep.duration : 0));
    this.draw();
    if (was) this.play();
  }

  now() { return this.posStart + Math.max(0, piano.ctx.currentTime - this.ctxStart) * this.speed; }
  toCtx(t) { return this.ctxStart + (t - this.posStart) / this.speed; }

  firstIndexFrom(t) {
    const n = this.prep.notes; let lo = 0, hi = n.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (n[mid].on < t) lo = mid + 1; else hi = mid; }
    return lo;
  }

  schedule() {
    const until = this.now() + LOOKAHEAD * this.speed;
    const notes = this.prep.notes;
    while (this.next < notes.length && notes[this.next].on < until) {
      const n = notes[this.next++];
      const voice = piano.play(n.pitch, n.vel, this.toCtx(n.on), n.soft);
      if (voice) {
        piano.release(voice, this.toCtx(n.sound));
        this.voices.push({ voice, end: n.sound });
      }
    }
    const t = this.now();
    this.voices = this.voices.filter((v) => v.end + 2 > t);
    if (t >= this.prep.duration) { this.pause(); this.pos = this.prep.duration; this.draw(); }
  }

  draw() {
    if (!this.prep) return;
    const t = this.pos, n = this.prep.notes;
    if (this.view && !this.$(".rp-3d").hidden) this.view.draw(t);
    if (!this.$(".rp-kbd").hidden) {
      const down = new Map();
      // Notes that could still be held at t start no earlier than t - maxHold.
      for (let i = this.firstIndexFrom(t + 1e-6) - 1; i >= 0 && n[i].on >= t - this.prep.maxHold; i--) {
        if (n[i].on <= t && t < n[i].off) down.set(n[i].pitch, Math.max(down.get(n[i].pitch) || 0, n[i].vel));
      }
      for (const [p, k] of Object.entries(this.keys)) {
        const v = down.get(+p);
        k.classList.toggle("on", v !== undefined);
        k.style.opacity = v !== undefined ? (0.45 + 0.55 * v / 127).toFixed(2) : "";
      }
    }
    const sus = this.prep.sustain.some(([a, b]) => a <= t && t < b);
    this.$(".rp-sus").classList.toggle("on", sus);
    const soft = n.some((x) => x.soft && x.on <= t && t < x.off);
    this.$(".rp-soft").classList.toggle("on", soft);
    const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
    this.$(".rp-time").textContent = `${fmt(t)} / ${fmt(this.prep.duration)}`;
    if (document.activeElement !== this.$(".rp-seek"))
      this.$(".rp-seek").value = this.prep.duration ? Math.round(1000 * t / this.prep.duration) : 0;
  }
}

// Loaded as a classic script: module scripts are fetched as CORS requests with an
// Origin header, which Cloudflare Access sends to its sign-in page instead.
window.Replay = Replay;
Replay.piano = piano; Replay.prepare = prepare;  // PROTOTYPE: for videoexport.js
})();
