// Smaller views: chroma bars, tuner needle, template scores, notes table, note chips.
import { NOTE_NAMES, fitCanvas, token } from "./spectrum.js";

export const ROLE_NAMES = ["root", "3rd", "5th", "7th", "other"];

export class ChromaView {
  constructor(canvas, tip) {
    this.canvas = canvas;
    this.tip = tip;
    this.hover = -1;
    this.bars = [];
    canvas.addEventListener("mousemove", (e) => {
      const r = canvas.getBoundingClientRect(), x = e.clientX - r.left;
      this.hover = this.bars.findIndex((b) => x >= b.x0 && x <= b.x1);
    });
    canvas.addEventListener("mouseleave", () => { this.hover = -1; tip.classList.add("hidden"); });
  }

  draw(chroma, roleOfPc, roleColor) {
    const { ctx, w, h } = fitCanvas(this.canvas);
    ctx.clearRect(0, 0, w, h);
    const p = { l: 8, r: 8, t: 8, b: 22 }, pw = w - p.l - p.r, ph = h - p.t - p.b;
    const slot = pw / 12, bw = Math.min(26, slot - 2);   // >= 2px surface gap between bars
    ctx.strokeStyle = token("--axis"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(p.l, p.t + ph + 0.5); ctx.lineTo(p.l + pw, p.t + ph + 0.5); ctx.stroke();
    ctx.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    this.bars = [];
    for (let i = 0; i < 12; i++) {
      const v = chroma ? chroma[i] : 0, cx = p.l + slot * (i + 0.5);
      const role = roleOfPc(i);
      const bh = Math.max(0, v) * ph;
      ctx.fillStyle = role < 4 ? roleColor(role) : token("--muted");
      ctx.globalAlpha = role < 4 ? 1 : 0.55;
      if (bh > 0.5) { topRounded(ctx, cx - bw / 2, p.t + ph - bh, bw, bh, Math.min(4, bh)); ctx.fill(); }
      ctx.globalAlpha = 1;
      ctx.fillStyle = role < 4 ? token("--text") : token("--muted");
      ctx.fillText(NOTE_NAMES[i], cx, h - 6);
      this.bars.push({ x0: cx - slot / 2, x1: cx + slot / 2, v, role, cx, y: p.t + ph - bh });
    }
    const b = this.bars[this.hover];
    if (b) {
      this.tip.innerHTML = `<b>${NOTE_NAMES[this.hover]}</b> ${b.v.toFixed(2)}` +
        (b.role < 4 ? ` <span class="muted">· ${ROLE_NAMES[b.role]} of chord</span>` : ` <span class="muted">· not a chord tone</span>`);
      this.tip.classList.remove("hidden");
      const tw = this.tip.offsetWidth;
      this.tip.style.left = Math.min(w - tw, Math.max(0, b.cx - tw / 2)) + "px";
      this.tip.style.top = Math.max(0, b.y - 40) + "px";
    }
  }
}

function topRounded(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x, y + h); ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r);
  ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r); ctx.lineTo(x + w, y + h); ctx.closePath();
}

// ------------------------------------------------------------------ tuner
export class TunerView {
  constructor(root) {
    this.needle = root.querySelector("#tuner-needle");
    this.status = root.querySelector("#tuner-status");
    this.cents = root.querySelector("#tuner-cents");
    this.hz = root.querySelector("#tuner-hz");
    this.string = root.querySelector("#tuner-string");
    const ticks = root.querySelector("#tuner-ticks");
    const ns = "http://www.w3.org/2000/svg";
    for (const c of [-50, -25, -10, 0, 10, 25, 50]) {
      const a = (c / 50) * 60 * (Math.PI / 180);
      const x1 = 150 + Math.sin(a) * 112, y1 = 110 - Math.cos(a) * 112;
      const x2 = 150 + Math.sin(a) * (c === 0 ? 92 : 100), y2 = 110 - Math.cos(a) * (c === 0 ? 92 : 100);
      const l = document.createElementNS(ns, "line");
      Object.entries({ x1, y1, x2, y2 }).forEach(([k, v]) => l.setAttribute(k, v));
      l.setAttribute("class", "tuner-tick" + (c === 0 ? " zero" : ""));
      ticks.appendChild(l);
      if (Math.abs(c) === 50 || Math.abs(c) === 25) {
        const t = document.createElementNS(ns, "text");
        t.setAttribute("x", 150 + Math.sin(a) * 86); t.setAttribute("y", 114 - Math.cos(a) * 86);
        t.setAttribute("class", "tuner-ticklabel"); t.textContent = (c > 0 ? "+" : "") + c;
        ticks.appendChild(t);
      }
    }
  }

  update(t) {
    if (!t) {
      this.needle.style.transform = "rotate(0deg)";
      this.status.textContent = "—"; this.status.className = "status";
      this.cents.textContent = "— cents"; this.hz.textContent = "— Hz"; this.string.textContent = "—";
      return;
    }
    const c = Math.max(-50, Math.min(50, t.cents));
    this.needle.style.transform = `rotate(${(c / 50) * 60}deg)`;
    const inTune = Math.abs(t.cents) <= 5;
    this.status.textContent = inTune ? "✓ in tune" : t.cents < 0 ? "▼ flat — tighten" : "▲ sharp — loosen";
    this.status.className = "status " + (inTune ? "good" : "warn");
    this.cents.textContent = `${t.cents >= 0 ? "+" : ""}${t.cents.toFixed(1)} cents`;
    this.hz.textContent = `${t.f0.toFixed(2)} Hz`;
    const sc = t.string_cents;
    this.string.textContent = Math.abs(sc) < 150
      ? `nearest open string ${t.string} (${sc >= 0 ? "+" : ""}${Math.round(sc)}¢)` : `fretted note`;
  }
}

// ------------------------------------------------------------------ lists
// Every list renders a fixed number of rows (blank ones as padding) so its card never
// changes height when results come and go; otherwise the whole page jumps.
const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
const pad = (rows, n, blank) => rows.concat(Array(Math.max(0, n - rows.length)).fill(blank)).join("");

const CAND_ROWS = 4, NOTE_ROWS = 6, HISTORY_ROWS = 8;

export function renderCandidates(el, chord) {
  const alts = (chord?.alts || []).slice(0, CAND_ROWS);
  el.innerHTML = pad(alts.map((a, i) => `
    <div class="cand${i === 0 ? " top" : ""}">
      <b>${esc(a.name)}</b>
      <div class="cand-bar"><i style="width:${Math.max(0, Math.min(1, a.score)) * 100}%"></i></div>
      <span class="num">${a.score.toFixed(2)}</span>
    </div>`), CAND_ROWS,
  `<div class="cand empty"><b>&nbsp;</b><div class="cand-bar"></div><span class="num"></span></div>`);
}

export function renderNotesTable(el, notes, roleColor) {
  el.innerHTML = pad(notes.slice(0, NOTE_ROWS).map((n) => `
    <tr>
      <td><b>${esc(n.name)}</b></td>
      <td><i class="sw sw-role" style="background:${roleColor(n.role)}"></i>${ROLE_NAMES[n.role]}</td>
      <td class="num">${n.freq.toFixed(1)}</td>
      <td class="num">${n.salience.toFixed(2)}</td>
      <td class="num">${n.harmonics.length}</td>
    </tr>`), NOTE_ROWS, `<tr class="empty"><td colspan="5"><b>&nbsp;</b></td></tr>`);
}

export const fmtTime = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

export function renderHistory(el, history) {
  const rows = history.slice(0, HISTORY_ROWS).map((h, i) => `
    <li class="${i === 0 ? "now" : ""}" style="opacity:${Math.max(0.45, 1 - i * 0.08)}">
      <b>${esc(h.name)}</b>
      <span class="long">${esc(h.long)}</span>
      <span class="num">${fmtTime(h.t)}</span>
      <span class="num">${Math.min(100, Math.round(h.score * 100))}%</span>
    </li>`);
  if (!rows.length) rows.push(`<li class="empty"><b>&nbsp;</b><span class="long">Strum a chord — each new one appears here</span></li>`);
  el.innerHTML = pad(rows, HISTORY_ROWS, `<li class="empty"><b>&nbsp;</b></li>`);
}

export function renderChips(el, notes, roleColor) {
  el.innerHTML = notes.map((n, i) => `
    <span class="chip${i === 0 ? " bass" : ""}" style="--c:${roleColor(n.role)}">
      <b>${esc(n.name)}</b><small>${i === 0 ? "bass · " : ""}${ROLE_NAMES[n.role]}</small>
    </span>`).join("");
}
