"""Frame-to-frame logic: adaptive noise gate, onset detection, smoothing and hold."""
from collections import Counter, deque

import numpy as np


class Tracker:
    def __init__(self, cfg, spectrum_freqs: np.ndarray):
        self.cfg = cfg
        self.noise_db = -60.0
        self.gate_open = False
        self._calib = []
        self._calib_frames = 0
        self.calibrate()

        band = (spectrum_freqs >= cfg.peak_fmin) & (spectrum_freqs <= cfg.peak_fmax)
        self._band = np.nonzero(band)[0]
        self._prev_db = None
        self._flux_hist = deque(maxlen=20)
        self._skip_until = -1.0
        self._last_onset = -1e9

        self._f0_hist = deque(maxlen=cfg.smooth_frames)
        self._chord_hist = deque(maxlen=cfg.smooth_frames)
        self.last = None
        self.last_t = -1e9
        self.last_chord_t = -1e9

    # ---------- noise gate ----------
    def calibrate(self):
        """Measure the room noise over the next calibrate_sec seconds."""
        self._calib = []
        self._calib_frames = max(1, int(self.cfg.calibrate_sec / self.cfg.hop_sec))

    @property
    def calibrating(self) -> bool:
        return self._calib_frames > 0

    @property
    def gate_db(self) -> float:
        return max(self.noise_db + self.cfg.gate_db_above_noise, self.cfg.gate_min_db)

    def update_gate(self, level_db: float) -> bool:
        if self._calib_frames > 0:
            self._calib.append(level_db)
            self._calib_frames -= 1
            if self._calib_frames == 0:
                self.noise_db = float(np.percentile(self._calib, 90))
            self.gate_open = False
            return False
        thr = self.gate_db - (self.cfg.gate_hysteresis_db if self.gate_open else 0.0)
        self.gate_open = level_db > thr
        return self.gate_open

    # ---------- onset (spectral flux) ----------
    def detect_onset(self, db: np.ndarray, t: float, gate_just_opened: bool) -> bool:
        cur = np.maximum(db[self._band], -100.0)
        flux = 0.0 if self._prev_db is None else float(np.mean(np.maximum(cur - self._prev_db, 0)))
        self._prev_db = cur
        median = float(np.median(self._flux_hist)) if self._flux_hist else flux
        self._flux_hist.append(flux)
        onset = gate_just_opened or (self.gate_open and flux > 2.0 * median + 1.0)
        # one strum = one onset: the 6 strings and the overlapping windows keep the flux
        # high for a few hops, so ignore re-triggers within 200 ms
        onset = onset and t - self._last_onset > 0.2
        if onset:
            self._last_onset = t
            self._skip_until = t + self.cfg.onset_skip_sec
            self._f0_hist.clear()
            self._chord_hist.clear()
        return onset

    def in_attack(self, t: float) -> bool:
        return t < self._skip_until

    # ---------- smoothing ----------
    def smooth_f0(self, f0):
        if f0 is None:
            return None
        self._f0_hist.append(f0)
        return float(np.median(self._f0_hist))

    def vote_chord(self, name):
        if name is None:
            return None
        self._chord_hist.append(name)
        counts = Counter(self._chord_hist).most_common()
        top = counts[0][1]
        winners = {n for n, c in counts if c == top}
        # tie -> most recent of the tied labels
        for n in reversed(self._chord_hist):
            if n in winners:
                return n
