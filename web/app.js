import { SpectrumView, SpectrogramView, token } from "./spectrum.js";
import { ChromaView, TunerView, fmtTime, renderCandidates, renderChips, renderHistory, renderNotesTable } from "./widgets.js";

const $ = (id) => document.getElementById(id);

const state = {
  ws: null,
  mode: "chord",
  frozen: false,
  frame: null,       // latest frame (what is drawn)
  fresh: false,      // a frame arrived since the last draw
  status: null,
  heroText: "—",     // last chord/note name shown, to animate changes
  history: [],       // recent chord changes, newest first
  cand: null,        // chord waiting to become stable enough to capture
  shown: null,       // chord mode: the captured frame every chord panel shows
  rendered: null,    // which captured frame the side lists were last rendered from
};

const spectrum = new SpectrumView($("spectrum"), $("spec-tip"));
const sgram = new SpectrogramView($("spectrogram"));
const chroma = new ChromaView($("chroma"), $("chroma-tip"));
const tuner = new TunerView($("tuner"));
spectrum.mode = state.mode;

// ------------------------------------------------------------------ helpers
let roleColors = [];
function refreshTokens() {
  roleColors = [0, 1, 2, 3, 4].map((i) => token(`--role-${i}`));
  sgram.buildLut();
  if (sgram.freqs) sgram.setFreqs(sgram.freqs);
}
const roleColor = (i) => roleColors[i ?? 4] || roleColors[4];

// chord function of a pitch class: index in chord.tones (root, 3rd, 5th, 7th) or 4
function roleOfPc(pc, frame) {
  if (state.mode === "tuner") {
    const t = frame?.tuner;
    return t && ((t.midi % 12) + 12) % 12 === pc ? 0 : 4;
  }
  const tones = frame?.chord?.tones;
  if (!tones) return 4;
  const i = tones.indexOf(pc);
  return i < 0 ? 4 : Math.min(i, 3);
}

function toast(msg, ms = 2600) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(obj));
}

// ------------------------------------------------------------------ websocket
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  state.ws = ws;
  ws.onopen = () => $("conn-dot").classList.add("ok");
  ws.onclose = () => {
    $("conn-dot").classList.remove("ok");
    $("source-label").textContent = "disconnected — retrying…";
    setTimeout(connect, 1000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "frame") onFrame(msg);
    else if (msg.type === "status") onStatus(msg);
    else if (msg.type === "file_ended") { $("player").pause(); toast("File finished — back to the microphone"); }
  };
}

function onStatus(s) {
  state.status = s;
  if (s.freqs) {
    spectrum.setFreqs(s.freqs);
    sgram.setFreqs(s.freqs);
  }
  spectrum.a4 = s.a4;
  $("a4-input").value = s.a4;
  $("gate-input").value = s.gate_db;
  $("gate-val").textContent = Math.round(s.gate_db);

  const src = s.source;
  const label = $("source-label");
  if (!src) label.textContent = s.mic_error ? `No microphone (${s.mic_error}) — upload a WAV` : "No input";
  else if (src.kind === "mic") label.textContent = `🎤 ${src.name} · ${src.fs} Hz`;
  else label.textContent = `▶ ${src.name}`;
  $("stop-file").classList.toggle("invisible", !src || src.kind !== "file");   // keeps its space: no top-bar jump
  if (s.mic_error && src?.kind !== "file") toast(`Microphone unavailable: ${s.mic_error}`, 5000);
}

function onFrame(f) {
  if (state.frozen) return;
  // annotate notes with their chord role once, for every view
  for (const n of f.notes || []) n.role = roleOfPc(((n.midi % 12) + 12) % 12, f);
  state.frame = f;
  state.fresh = true;
  if (capture(f)) renderHistory($("history"), state.history);
  spectrum.updateRange(f.spectrum);
  if (state.shown) spectrum.updateRange(state.shown.spectrum);   // keep the captured line on-scale
  spectrum.pushHold(f.spectrum);
  sgram.push(f, spectrum.top, spectrum.span);
  updateText(f);
}

// Single-chord demo: a chord is captured once it has been stable for CAPTURE_STABLE frames
// (0.3 s) and then stays on screen until a *different* chord is captured, so viewers have time
// to read it. Brief flips while a chord rings (C -> C/G -> C) never get that far. While the same
// chord rings on, the richest frame (most notes, then loudest) is kept: the clearest spectrum.
// Times are seconds since the page loaded (the server's frame clock restarts with every source,
// e.g. when a WAV ends and the mic takes over). Returns true if the history list changed.
const CAPTURE_STABLE = 6;
const now = () => performance.now() / 1000;
function capture(f) {
  const c = f.chord, h = state.history, s = state.shown;
  if (!c || f.held || c.name === "N.C.") { state.cand = null; return false; }
  if (s && s.chord.name === c.name) {
    const n = f.notes.length, sn = s.notes.length;
    if (n > sn || (n === sn && f.level_db > s.level_db)) state.shown = { ...f, since: s.since };
    state.cand = null;
    return false;
  }
  if (state.cand?.name !== c.name) state.cand = { name: c.name, t: now(), n: 0 };
  if (++state.cand.n < CAPTURE_STABLE) return false;
  state.shown = { ...f, since: state.cand.t };
  state.cand = null;
  if (c.long === "single note" || h[0]?.name === c.name) return false;
  h.unshift({ name: c.name, long: c.long, score: c.score, t: state.shown.since });
  if (h.length > 8) h.pop();
  return true;
}

// ------------------------------------------------------------------ text panels
function updateText(f) {
  const hero = $("hero");
  const hv = $("hero-value");
  const meta = [];
  if (f.calibrating) meta.push("calibrating noise floor — keep quiet…");

  if (state.mode === "chord") {
    const s = state.shown, c = s?.chord;
    const stale = !!s && !f.gate_open;                              // sound has died away
    hero.classList.toggle("stale", stale);
    $("hero-label").textContent = stale ? "Last chord" : "Chord";
    hv.textContent = c ? c.name : "—";
    $("hero-long").textContent = c ? (c.long === "single note" ? "single note (all octaves)" : c.long) : (f.gate_open ? "listening…" : "Strum a chord");
    if (c) {
      if (c.alts.length) meta.push(`match ${Math.min(100, c.score * 100).toFixed(0)}%`);   // bass bonus can push it past 1
      meta.push(`heard at ${fmtTime(s.since)}`);
    }
    if (state.rendered !== s) {                                     // only when the capture changes
      state.rendered = s;
      renderChips($("note-chips"), s?.notes || [], roleColor);
      renderCandidates($("candidates"), c);
      renderNotesTable($("notes-body"), s?.notes || [], roleColor);
    }
  } else {
    const t = f.tuner;
    hero.classList.remove("stale");
    $("hero-label").textContent = "Note";
    hv.textContent = t ? t.note : "—";
    $("hero-long").textContent = t ? `${t.f0.toFixed(2)} Hz` : (f.gate_open ? "listening…" : "Pluck one string");
    tuner.update(t);
    if (t) meta.push(`harmonic energy ${(t.confidence * 100).toFixed(0)}%`);
    if (f.held) meta.push("holding last result");
    state.rendered = "tuner";
    renderCandidates($("candidates"), null);
    renderNotesTable($("notes-body"), f.notes || [], roleColor);
  }
  hv.classList.toggle("empty", hv.textContent === "—");
  hv.classList.toggle("long", hv.textContent.length > 4);          // e.g. C#maj7: smaller, same box
  if (hv.textContent !== state.heroText) {
    state.heroText = hv.textContent;
    hv.classList.remove("pop");
    if (hv.textContent !== "—") { void hv.offsetWidth; hv.classList.add("pop"); }   // reflow restarts the animation
  }
  if (f.file_pos != null) meta.push(`file ${f.file_pos.toFixed(1)} s`);
  $("hero-meta").textContent = meta.join(" · ") || " ";       // keep the line's height when empty

  // level meter: -90..0 dBFS
  const pct = (db) => Math.max(0, Math.min(100, ((db + 90) / 90) * 100));
  $("meter-fill").style.width = pct(f.level_db) + "%";
  $("meter-fill").classList.toggle("open", f.gate_open);
  $("meter-gate").style.left = pct(f.gate_db) + "%";
  $("meter-label").textContent = `${f.level_db.toFixed(0)} dB · gate ${f.gate_open ? "open" : "closed"}`;
}

// ------------------------------------------------------------------ render loop
function render() {
  const f = state.frame;
  const shown = state.mode === "chord" ? state.shown : null;
  spectrum.draw(f, roleColor, shown);       // every frame: keeps hover responsive while frozen
  if (state.fresh || !f) sgram.draw();
  const cf = shown || f;                    // chroma of the captured chord, live before the first one
  chroma.draw(cf?.chroma, (pc) => roleOfPc(pc, cf), roleColor);
  state.fresh = false;
  requestAnimationFrame(render);
}

// ------------------------------------------------------------------ controls
function setMode(mode) {
  state.mode = mode;
  spectrum.mode = mode;
  document.querySelectorAll(".seg-btn").forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on);
  });
  $("tuner").classList.toggle("hidden", mode !== "tuner");
  $("note-chips").classList.toggle("hidden", mode !== "chord");
  $("lg-captured").classList.toggle("hidden", mode !== "chord");
  for (const fr of [state.frame, state.shown]) {
    for (const n of fr?.notes || []) n.role = roleOfPc(((n.midi % 12) + 12) % 12, fr);
  }
  state.rendered = undefined;               // force the side lists to re-render for this mode
  if (state.frame) updateText(state.frame);
}
document.querySelectorAll(".seg-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

function toggleFreeze() {
  state.frozen = !state.frozen;
  $("btn-freeze").classList.toggle("active", state.frozen);
  $("btn-freeze").textContent = state.frozen ? "Frozen" : "Freeze";
  $("frozen-badge").classList.toggle("hidden", !state.frozen);
}
$("btn-freeze").addEventListener("click", toggleFreeze);
$("btn-clear-history").addEventListener("click", () => { state.history.length = 0; state.cand = null; renderHistory($("history"), state.history); });

function setPresent(on) {
  document.documentElement.classList.toggle("present", on);
  $("btn-present").classList.toggle("active", on);
  $("btn-present").setAttribute("aria-pressed", on);
  try { localStorage.setItem("present", on ? "1" : "0"); } catch { /* private mode */ }
}
const togglePresent = () => setPresent(!document.documentElement.classList.contains("present"));
$("btn-present").addEventListener("click", togglePresent);

function calibrate() { send({ cmd: "calibrate" }); toast("Calibrating noise floor — stay quiet for 1 s"); }
$("btn-calibrate").addEventListener("click", calibrate);

$("file-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    playLocal(URL.createObjectURL(file));
    toast(`Playing ${j.name} (${j.duration} s)`);
  } catch (err) {
    toast(`Upload failed: ${err.message}`, 5000);
  }
});

function playLocal(url) {
  const p = $("player");
  p.src = url;
  p.currentTime = 0;
  p.play().catch(() => {});      // analysis still runs if the browser blocks audio
}

$("stop-file").addEventListener("click", () => { send({ cmd: "stop_file" }); $("player").pause(); });

$("btn-record").addEventListener("click", async () => {
  try {
    const r = await fetch("/api/record?sec=5&label=" + encodeURIComponent(state.frame?.chord?.name || ""), { method: "POST" });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    toast(`Saved ${j.name}`);
    loadRecordings();
  } catch (err) {
    toast(`Recording failed: ${err.message}`, 5000);
  }
});

async function loadRecordings() {
  try {
    const j = await (await fetch("/api/recordings")).json();
    const sel = $("rec-select");
    sel.innerHTML = `<option value="">— play a recording —</option>` +
      j.recordings.map((r) => `<option value="${encodeURIComponent(r.name)}">${r.name.replace(/</g, "&lt;")}</option>`).join("");
  } catch { /* server not up yet */ }
}
$("rec-select").addEventListener("change", async (e) => {
  const name = e.target.value;
  if (!name) return;
  e.target.value = "";
  const r = await fetch(`/api/play/${name}`, { method: "POST" });
  const j = await r.json();
  if (!r.ok) { toast(`Cannot play: ${j.detail}`, 5000); return; }
  playLocal(`/recordings/${name}`);
  toast(`Playing ${j.name}`);
});

async function loadDevices() {
  try {
    const j = await (await fetch("/api/devices")).json();
    const sel = $("device-select");
    sel.innerHTML = `<option value="">System default</option>` + j.devices.map((d) =>
      `<option value="${d.id}" ${d.id === j.current ? "selected" : ""}>${d.name.replace(/</g, "&lt;")} (${d.api}, ${d.samplerate} Hz)${d.default ? " ★" : ""}</option>`).join("");
  } catch { /* ignore */ }
}
$("device-select").addEventListener("change", (e) => { send({ cmd: "device", value: e.target.value }); toast("Switching input — calibrating"); });
$("a4-input").addEventListener("change", (e) => send({ cmd: "a4", value: parseFloat(e.target.value) || 440 }));
$("gate-input").addEventListener("input", (e) => { $("gate-val").textContent = e.target.value; });
$("gate-input").addEventListener("change", (e) => send({ cmd: "gate", value: parseFloat(e.target.value) }));
$("show-hps").addEventListener("change", (e) => { spectrum.showHps = e.target.checked; $("lg-hps").classList.toggle("hidden", !e.target.checked); });
$("show-floor").addEventListener("change", (e) => { spectrum.showFloor = e.target.checked; $("lg-floor").classList.toggle("hidden", !e.target.checked); });
document.querySelector(".settings").addEventListener("toggle", (e) => { if (e.target.open) { loadDevices(); loadRecordings(); } });

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("theme", t); } catch { /* private mode */ }
  refreshTokens();
}
$("btn-theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.code === "Space") { e.preventDefault(); toggleFreeze(); }
  else if (e.key === "c" || e.key === "C") calibrate();
  else if (e.key === "t" || e.key === "T") setMode(state.mode === "chord" ? "tuner" : "chord");
  else if (e.key === "p" || e.key === "P") togglePresent();
});

// ------------------------------------------------------------------ start
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }
try { if (localStorage.getItem("present") === "1") setPresent(true); } catch { /* ignore */ }
refreshTokens();
setMode("chord");
renderHistory($("history"), state.history);
renderChips($("note-chips"), [], roleColor);
renderCandidates($("candidates"), null);
renderNotesTable($("notes-body"), [], roleColor);
connect();
loadRecordings();
requestAnimationFrame(render);
