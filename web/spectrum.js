// Spectrum and spectrogram canvases (no libraries, works offline).
export const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const OPEN_STRINGS = { 40: "E2", 45: "A2", 50: "D3", 55: "G3", 59: "B3", 64: "E4" };
const FREQ_TICKS = [100, 200, 500, 1000, 2000, 4000];

export function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr;
    canvas.height = h * dpr;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

export function freqToMidi(f, a4 = 440) { return 69 + 12 * Math.log2(f / a4); }
export function midiToName(m) { return NOTE_NAMES[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1); }
function fmtHz(f) { return f >= 1000 ? (f / 1000).toFixed(f >= 10000 ? 0 : 1) + "k" : String(Math.round(f)); }

// nearest index in an ascending array
function nearestIndex(arr, v) {
  let lo = 0, hi = arr.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < v) lo = mid; else hi = mid;
  }
  return Math.abs(arr[lo] - v) <= Math.abs(arr[hi] - v) ? lo : hi;
}

export class SpectrumView {
  constructor(canvas, tip) {
    this.canvas = canvas;
    this.tip = tip;
    this.freqs = null;
    this.hold = null;
    this.top = -20;
    this.span = 90;
    this.mouse = null;
    this.a4 = 440;
    this.showHps = false;
    this.showFloor = true;
    this.pad = { l: 44, r: 12, t: 30, b: 26 };
    canvas.addEventListener("mousemove", (e) => {
      const r = canvas.getBoundingClientRect();
      this.mouse = { x: e.clientX - r.left, y: e.clientY - r.top };
    });
    canvas.addEventListener("mouseleave", () => { this.mouse = null; tip.classList.add("hidden"); });
  }

  setFreqs(freqs) {
    this.freqs = freqs;
    this.fmin = freqs[0];
    this.fmax = freqs[freqs.length - 1];
    this.hold = null;
  }

  get bottom() { return this.top - this.span; }

  // Auto range: jump up immediately, relax down slowly, so the plot never clips
  updateRange(spec) {
    let mx = -200;
    for (const v of spec) if (v > mx) mx = v;
    const target = Math.min(10, Math.max(-50, Math.ceil((mx + 8) / 10) * 10));
    if (target > this.top) this.top = target;
    else this.top = Math.max(target, this.top - 0.15);
  }

  dbAt(spec, f) { return spec[nearestIndex(this.freqs, f)]; }

  // `captured` (optional): the frame the current chord was captured from. Its spectrum is drawn
  // as a second line and the note markers sit on it, so they stay readable after the sound fades.
  draw(frame, roleColor, captured = null) {
    const { ctx, w, h } = fitCanvas(this.canvas);
    const p = this.pad, pw = w - p.l - p.r, ph = h - p.t - p.b;
    const X = (f) => p.l + (Math.log(f / this.fmin) / Math.log(this.fmax / this.fmin)) * pw;
    const Y = (db) => p.t + ((this.top - db) / this.span) * ph;
    const c = {
      grid: token("--grid"), axis: token("--axis"), muted: token("--muted"), text: token("--text"),
      text2: token("--text-2"), line: token("--spec-line"), fill: token("--spec-fill"),
      hold: token("--spec-hold"), floor: token("--spec-floor"), hps: token("--hps"), surface: token("--surface"),
      captured: token("--spec-captured"),
    };
    ctx.clearRect(0, 0, w, h);
    if (!this.freqs) return;
    ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";

    // --- grid: faint semitone lines, open strings labelled, dB lines every 20 dB
    for (let m = Math.ceil(freqToMidi(this.fmin, this.a4)); m <= freqToMidi(this.fmax, this.a4); m++) {
      const x = X(this.a4 * 2 ** ((m - 69) / 12));
      const open = OPEN_STRINGS[m];
      ctx.strokeStyle = c.grid;
      ctx.globalAlpha = open ? 1 : 0.45;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x + 0.5, p.t); ctx.lineTo(x + 0.5, p.t + ph); ctx.stroke();
      ctx.globalAlpha = 1;
      if (open && pw > 500) {             // labels would collide with the Hz ticks on phones
        ctx.fillStyle = c.muted; ctx.textAlign = "center";
        ctx.fillText(open, x, p.t + ph + 22);
      }
    }
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (let db = Math.floor(this.top / 20) * 20; db >= this.bottom; db -= 20) {
      const y = Y(db);
      ctx.strokeStyle = c.grid; ctx.beginPath(); ctx.moveTo(p.l, y + 0.5); ctx.lineTo(p.l + pw, y + 0.5); ctx.stroke();
      ctx.fillStyle = c.muted; ctx.fillText(`${db} dB`, p.l - 6, y);
    }
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    for (const f of FREQ_TICKS) {
      if (f < this.fmin || f > this.fmax) continue;
      ctx.fillStyle = c.muted; ctx.fillText(fmtHz(f) + (f === 100 ? " Hz" : ""), X(f), p.t + ph + 11);
    }
    ctx.strokeStyle = c.axis;
    ctx.beginPath(); ctx.moveTo(p.l, p.t + ph + 0.5); ctx.lineTo(p.l + pw, p.t + ph + 0.5); ctx.stroke();

    if (!frame) return;
    const spec = frame.spectrum;
    const n = spec.length;
    const clampY = (db) => Math.min(p.t + ph, Math.max(p.t, Y(db)));

    ctx.save();
    ctx.beginPath(); ctx.rect(p.l, p.t, pw, ph); ctx.clip();

    // --- noise floor
    if (this.showFloor && frame.floor) {
      ctx.setLineDash([4, 4]); ctx.strokeStyle = c.floor; ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < n; i++) { const x = X(this.freqs[i]), y = clampY(frame.floor[i]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      ctx.stroke(); ctx.setLineDash([]);
    }

    // --- spectrum: filled area + 2px line
    ctx.beginPath();
    ctx.moveTo(X(this.freqs[0]), p.t + ph);
    for (let i = 0; i < n; i++) ctx.lineTo(X(this.freqs[i]), clampY(spec[i]));
    ctx.lineTo(X(this.freqs[n - 1]), p.t + ph);
    ctx.closePath();
    ctx.fillStyle = c.fill; ctx.fill();
    ctx.beginPath();
    for (let i = 0; i < n; i++) { const x = X(this.freqs[i]), y = clampY(spec[i]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.strokeStyle = c.line; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();

    // --- peak hold (decays 0.4 dB per drawn frame)
    if (this.hold) {
      ctx.beginPath();
      for (let i = 0; i < n; i++) { const x = X(this.freqs[i]), y = clampY(this.hold[i]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      ctx.strokeStyle = c.hold; ctx.lineWidth = 1; ctx.globalAlpha = 0.7; ctx.stroke(); ctx.globalAlpha = 1;
    }

    // --- captured chord spectrum
    if (captured?.spectrum?.length === n) {
      ctx.beginPath();
      for (let i = 0; i < n; i++) { const x = X(this.freqs[i]), y = clampY(captured.spectrum[i]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      ctx.strokeStyle = c.captured; ctx.lineWidth = 1.5; ctx.globalAlpha = 0.9; ctx.stroke(); ctx.globalAlpha = 1;
    }

    // --- HPS curve (0..1) scaled into the plot
    if (this.showHps && frame.hps) {
      ctx.beginPath();
      for (let i = 0; i < n; i++) { const x = X(this.freqs[i]), y = p.t + ph - frame.hps[i] * ph * 0.9; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      ctx.strokeStyle = c.hps; ctx.lineWidth = 1.5; ctx.stroke();
    }
    ctx.restore();

    // --- detected fundamentals + their harmonics
    const src = captured?.spectrum?.length === n ? captured : frame;
    const markers = this.markers(src, roleColor);
    const rows = [];
    for (const m of markers.sort((a, b) => a.f - b.f)) {
      const x = X(m.f);
      if (x < p.l || x > p.l + pw) continue;
      ctx.strokeStyle = m.color; ctx.lineWidth = 2; ctx.globalAlpha = 0.85;
      ctx.beginPath(); ctx.moveTo(x, p.t); ctx.lineTo(x, clampY(this.dbAt(src.spectrum, m.f))); ctx.stroke();
      ctx.globalAlpha = 1;
      for (const hf of m.harmonics) {
        const hx = X(hf);
        if (hx < p.l || hx > p.l + pw) continue;
        ctx.beginPath(); ctx.arc(hx, clampY(this.dbAt(src.spectrum, hf)), 4, 0, 2 * Math.PI);
        ctx.fillStyle = m.color; ctx.fill();
        ctx.lineWidth = 2; ctx.strokeStyle = c.surface; ctx.stroke();
      }
      // label, staggered into rows so neighbours never collide
      ctx.font = "600 12px system-ui, -apple-system, 'Segoe UI', sans-serif";
      const tw = ctx.measureText(m.label).width + 10;
      let row = 0;
      while (rows[row] !== undefined && rows[row] > x - tw / 2 - 2) row++;
      rows[row] = x + tw / 2;
      // row 0 sits in the strip above the plot; further rows step down inside it
      const by = row === 0 ? 6 : p.t + 4 + (row - 1) * 20;
      ctx.fillStyle = m.color;
      roundRect(ctx, x - tw / 2, by, tw, 18, 4); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(m.label, x, by + 9.5);
      ctx.textBaseline = "alphabetic";
    }
    ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";

    // --- hover crosshair + tooltip
    if (this.mouse && this.mouse.x >= p.l && this.mouse.x <= p.l + pw) {
      const f = this.fmin * Math.exp(((this.mouse.x - p.l) / pw) * Math.log(this.fmax / this.fmin));
      const db = this.dbAt(spec, f);
      ctx.strokeStyle = c.text2; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(this.mouse.x + 0.5, p.t); ctx.lineTo(this.mouse.x + 0.5, p.t + ph); ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(this.mouse.x, clampY(db), 4, 0, 2 * Math.PI); ctx.fillStyle = c.line; ctx.fill();
      const mm = freqToMidi(f, this.a4), r = Math.round(mm), cents = Math.round((mm - r) * 100);
      const near = this.nearestPeak(frame, f);
      this.tip.innerHTML =
        `<b>${f.toFixed(1)} Hz</b> <span class="muted">≈ ${midiToName(r)} ${cents >= 0 ? "+" : ""}${cents}¢</span><br>` +
        `${db.toFixed(1)} dB` + (near ? `<br><span class="muted">peak ${near[0].toFixed(2)} Hz, ${near[1].toFixed(1)} dB</span>` : "");
      this.tip.classList.remove("hidden");
      const tx = this.mouse.x + 14, tw = this.tip.offsetWidth;
      this.tip.style.left = (tx + tw > w ? this.mouse.x - tw - 14 : tx) + "px";
      this.tip.style.top = Math.max(0, this.mouse.y - 40) + "px";
    }
  }

  nearestPeak(frame, f) {
    let best = null, bd = Infinity;
    for (const pk of frame.peaks || []) {
      const d = Math.abs(Math.log2(pk[0] / f)) * 1200;
      if (d < bd && d < 60) { bd = d; best = pk; }
    }
    return best;
  }

  markers(frame, roleColor) {
    if (this.mode === "tuner") {
      const t = frame.tuner;
      if (!t) return [];
      return [{ f: t.f0, label: t.note, color: roleColor(0), harmonics: t.harmonics.slice(1, 10) }];
    }
    return (frame.notes || []).map((nt) => ({
      f: nt.freq, label: nt.name, color: roleColor(nt.role ?? 4), harmonics: nt.harmonics.slice(1),
    }));
  }

  pushHold(spec) {
    if (!this.hold || this.hold.length !== spec.length) this.hold = spec.slice();
    for (let i = 0; i < spec.length; i++) this.hold[i] = Math.max(spec[i], this.hold[i] - 0.4);
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

// ------------------------------------------------------------------ spectrogram
const SG_COLS = 200;   // 10 s at 20 frames/s

function hexToRgb(hex) {
  const v = parseInt(hex.replace("#", ""), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

export class SpectrogramView {
  constructor(canvas) {
    this.canvas = canvas;
    this.off = document.createElement("canvas");
    this.img = null;
    this.onsets = [];
    this.pad = { l: 44, r: 12, t: 8, b: 20 };
    this.buildLut();
  }

  // one-hue sequential ramp (blue), from the surface colour up to the lightest step
  buildLut() {
    const stops = [token("--surface") || "#1a1a19", "#104281", "#256abf", "#3987e5", "#86b6ef", "#cde2fb"];
    const rgb = stops.map(hexToRgb);
    this.lut = new Uint8ClampedArray(256 * 3);
    for (let i = 0; i < 256; i++) {
      const t = (i / 255) * (rgb.length - 1), k = Math.min(rgb.length - 2, Math.floor(t)), u = t - k;
      for (let ch = 0; ch < 3; ch++) this.lut[i * 3 + ch] = rgb[k][ch] + (rgb[k + 1][ch] - rgb[k][ch]) * u;
    }
    if (this.img) this.img.data.fill(0);
  }

  setFreqs(freqs) {
    this.freqs = freqs;
    this.off.width = SG_COLS;
    this.off.height = freqs.length;
    this.img = new ImageData(SG_COLS, freqs.length);
    const bg = this.lut;
    for (let i = 0; i < this.img.data.length; i += 4) {
      this.img.data[i] = bg[0]; this.img.data[i + 1] = bg[1]; this.img.data[i + 2] = bg[2]; this.img.data[i + 3] = 255;
    }
  }

  push(frame, top, span) {
    if (!this.img) return;
    const rows = this.freqs.length, d = this.img.data, rowBytes = SG_COLS * 4;
    for (let r = 0; r < rows; r++) d.copyWithin(r * rowBytes, r * rowBytes + 4, (r + 1) * rowBytes);
    const bottom = top - span * 0.8;           // only the upper 80 % of the range gets colour
    for (let r = 0; r < rows; r++) {
      const db = frame.spectrum[rows - 1 - r];
      const v = Math.max(0, Math.min(255, Math.round(((db - bottom) / (top - bottom)) * 255)));
      const o = r * rowBytes + (SG_COLS - 1) * 4;
      d[o] = this.lut[v * 3]; d[o + 1] = this.lut[v * 3 + 1]; d[o + 2] = this.lut[v * 3 + 2]; d[o + 3] = 255;
    }
    this.onsets = this.onsets.map((c) => c - 1).filter((c) => c >= 0);
    if (frame.onset) this.onsets.push(SG_COLS - 1);
  }

  draw() {
    const { ctx, w, h } = fitCanvas(this.canvas);
    ctx.clearRect(0, 0, w, h);
    if (!this.img) return;
    const p = this.pad, pw = w - p.l - p.r, ph = h - p.t - p.b;
    this.off.getContext("2d").putImageData(this.img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(this.off, p.l, p.t, pw, ph);

    const fmin = this.freqs[0], fmax = this.freqs[this.freqs.length - 1];
    const Y = (f) => p.t + ph - (Math.log(f / fmin) / Math.log(fmax / fmin)) * ph;
    ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.fillStyle = token("--muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const f of [100, 200, 500, 1000, 2000]) ctx.fillText(fmtHz(f), p.l - 6, Y(f));
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    ctx.fillText("−10 s", p.l, h - 4);
    ctx.textAlign = "right"; ctx.fillText("now", p.l + pw, h - 4);
    ctx.textAlign = "center"; ctx.fillText("▲ onset detected", p.l + pw / 2, h - 4);

    ctx.fillStyle = token("--warning");
    for (const col of this.onsets) {
      const x = p.l + ((col + 0.5) / SG_COLS) * pw;
      ctx.beginPath(); ctx.moveTo(x - 4, p.t + ph); ctx.lineTo(x + 4, p.t + ph); ctx.lineTo(x, p.t + ph - 7); ctx.closePath(); ctx.fill();
    }
  }
}
