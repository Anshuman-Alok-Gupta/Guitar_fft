"""Glue: one call per audio frame -> everything the UI needs, as plain JSON-able data."""
import numpy as np

from .chord import chroma, name_chord
from .config import Config
from .multipitch import detect_notes
from .notes import describe, nearest_string
from .pitch import detect_pitch, harmonic_product_spectrum
from .spectrum import EPS, SpectrumAnalyzer
from .tracker import Tracker

DISPLAY_FMIN, DISPLAY_FMAX, DISPLAY_BINS = 60.0, 4000.0, 512


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


class Analyzer:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.sa = SpectrumAnalyzer(self.cfg.n_win, self.cfg.fs)
        self.tracker = Tracker(self.cfg, self.sa.freqs)
        self._frame = 0
        self._chord_cache = {}

        # Log-spaced display grid; each cell shows the max of the FFT bins it covers
        # (interpolated where a cell is narrower than one bin, i.e. at low frequencies).
        edges = np.geomspace(DISPLAY_FMIN, DISPLAY_FMAX, DISPLAY_BINS + 1)
        self.display_freqs = np.sqrt(edges[:-1] * edges[1:])
        lo = np.ceil(edges[:-1] / self.sa.df).astype(int)
        hi = np.ceil(edges[1:] / self.sa.df).astype(int)
        self._pool = np.nonzero(hi > lo)[0]
        self._pool_idx = np.column_stack([lo[self._pool], hi[self._pool]]).ravel()

    # ---------- helpers ----------
    def _to_display(self, freqs, values):
        out = np.interp(self.display_freqs, freqs, values)
        if self._pool.size and self._pool_idx[-1] < len(values):
            out[self._pool] = np.maximum.reduceat(values, self._pool_idx)[::2]
        return out

    def set_a4(self, a4: float):
        self.cfg.a4 = float(a4)

    def calibrate(self):
        self.tracker.calibrate()

    # ---------- main entry ----------
    def process(self, x: np.ndarray, t: float | None = None) -> dict:
        cfg, tr = self.cfg, self.tracker
        if t is None:
            t = self._frame * cfg.hop_sec
        self._frame += 1

        x = np.asarray(x, dtype=float)
        level_db = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + EPS)
        was_open = tr.gate_open
        gate = tr.update_gate(level_db)

        spec = self.sa.compute(x)
        onset = tr.detect_onset(spec.db, t, gate and not was_open)
        peaks = self.sa.find_peaks(spec, cfg.peak_fmin, cfg.peak_fmax, cfg.peak_db_above_floor,
                                   cfg.peak_dynamic_range_db, cfg.max_peaks)
        fh, hps = harmonic_product_spectrum(spec, cfg.hps_harmonics)

        held = False
        if gate and not tr.in_attack(t):
            result = self._analyse(spec, peaks, (fh, hps))
            if result["chord"] is not None:
                tr.last_chord_t = t
            elif tr.last and tr.last["chord"] and t - tr.last_chord_t < cfg.hold_sec:
                # one ambiguous frame between strums: keep showing the previous chord
                result["chord"] = tr.last["chord"]
            if result["tuner"] or result["notes"]:
                tr.last, tr.last_t = result, t
            elif tr.last is not None:
                result, held = tr.last, True
        elif tr.last is not None and (gate or t - tr.last_t < cfg.hold_sec):
            result, held = tr.last, not gate
        else:
            result = {"tuner": None, "notes": [], "chroma": [0.0] * 12, "chord": None}

        # HPS on the display grid, scaled 0..1 over the fundamental search range
        hps_disp = self._to_display(fh, hps)
        rng = (self.display_freqs >= cfg.fmin) & (self.display_freqs <= cfg.fmax)
        lo, hi = hps_disp[rng].min(), hps_disp[rng].max()
        hps_disp = np.clip((hps_disp - lo) / (hi - lo + EPS), 0, 1)

        order = np.argsort(peaks.db)[::-1][:40]
        return {
            "t": _r(t, 3),
            "level_db": _r(level_db),
            "noise_db": _r(tr.noise_db),
            "gate_db": _r(tr.gate_db),
            "gate_open": bool(gate),
            "calibrating": tr.calibrating,
            "onset": bool(onset),
            "held": held,
            "spectrum": [round(v, 1) for v in self._to_display(spec.freqs, spec.db).tolist()],
            "floor": [round(v, 1) for v in np.interp(self.display_freqs, spec.freqs, spec.floor_db).tolist()],
            "hps": [round(v, 3) for v in hps_disp.tolist()],
            "peaks": [[_r(peaks.freq[i], 2), _r(peaks.db[i])] for i in order],
            **result,
        }

    def _analyse(self, spec, peaks, hps_result) -> dict:
        cfg, tr = self.cfg, self.tracker

        tuner = detect_pitch(spec, peaks, cfg, hps_result)
        if tuner:
            f0 = tr.smooth_f0(tuner["f0"])
            midi, name, cents = describe(f0, cfg.a4)
            string, string_cents = nearest_string(f0, cfg.a4)
            tuner = {
                "f0": _r(f0, 2), "midi": midi, "note": name, "cents": _r(cents),
                "string": string, "string_cents": _r(string_cents),
                "confidence": _r(tuner["confidence"], 2),
                "harmonics": [_r(h * f0, 1) for h in range(1, int(cfg.peak_fmax / f0) + 1)],
            }

        notes = detect_notes(peaks, cfg)
        for n in notes:
            n["freq"] = _r(n["freq"], 2)
            n["salience"] = _r(n["salience"], 2)
            n["harmonics"] = [_r(f, 1) for f in n["harmonics"]]
        chroma_vec = chroma(peaks, cfg)
        chord = name_chord(chroma_vec, notes, cfg)
        if chord:
            chord["score"] = _r(chord["score"], 3)
            for a in chord["alts"]:
                a["score"] = _r(a["score"], 3)
            self._chord_cache[chord["name"]] = chord
            voted = tr.vote_chord(chord["name"])
            chord = self._chord_cache.get(voted, chord)

        return {"tuner": tuner, "notes": notes,
                "chroma": [round(v, 3) for v in chroma_vec.tolist()], "chord": chord}
