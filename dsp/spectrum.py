"""Windowed FFT, noise-floor estimate and spectral peak picking."""
from dataclasses import dataclass

import numpy as np

EPS = 1e-12


@dataclass
class Spectrum:
    freqs: np.ndarray    # bin centre frequencies (Hz)
    mag: np.ndarray      # linear magnitude, scaled so a full-scale sine reads ~1.0
    db: np.ndarray       # 20*log10(mag)
    floor_db: np.ndarray # smooth estimate of the noise floor under the peaks
    df: float            # bin spacing (Hz)


@dataclass
class Peaks:
    freq: np.ndarray     # interpolated peak frequencies (Hz), ascending
    db: np.ndarray       # interpolated peak level (dB)
    amp: np.ndarray      # same level as linear magnitude
    above_floor: np.ndarray  # dB above the local noise floor


class SpectrumAnalyzer:
    """Pre-computes everything that only depends on the window length, so each frame
    costs one multiply and one FFT."""

    def __init__(self, n: int, fs: int):
        self.n = n
        self.fs = fs
        self.window = np.hanning(n)
        # 2x zero padding: a smoother grid for peak picking; precision comes from interpolation
        self.nfft = 1 << int(np.ceil(np.log2(2 * n)))
        self.df = fs / self.nfft
        self.freqs = np.arange(self.nfft // 2 + 1) * self.df
        self.scale = 2.0 / self.window.sum()   # undo the window's coherent gain

        # Noise floor: low percentile of the dB spectrum in half-octave-spaced, one-octave-wide
        # bands, then interpolated back to every bin on a log-frequency axis.
        centres = 40.0 * 2 ** (np.arange(0, 40) / 2)
        self._floor_centres = centres[centres < fs / 2]
        self._floor_bands = []
        for fc in self._floor_centres:
            lo = int(fc / np.sqrt(2) / self.df)
            hi = max(int(fc * np.sqrt(2) / self.df), lo + 8)
            self._floor_bands.append((lo, min(hi, len(self.freqs))))
        self._log_f = np.log2(np.maximum(self.freqs, 1.0))

    def compute(self, x: np.ndarray) -> Spectrum:
        x = np.asarray(x, dtype=float)
        x = (x - x.mean()) * self.window            # remove DC, taper the edges
        mag = np.abs(np.fft.rfft(x, self.nfft)) * self.scale
        db = 20 * np.log10(mag + EPS)

        band_floor = np.array([np.percentile(db[lo:hi], 30) for lo, hi in self._floor_bands])
        floor_db = np.interp(self._log_f, np.log2(self._floor_centres), band_floor)
        return Spectrum(self.freqs, mag, db, floor_db, self.df)

    def find_peaks(self, s: Spectrum, fmin, fmax, db_above_floor, dyn_range_db, max_peaks) -> Peaks:
        db = s.db
        lo = max(int(fmin / s.df), 1)
        hi = min(int(fmax / s.df) + 1, len(db) - 1)
        c = db[lo:hi]
        left, right = db[lo - 1:hi - 1], db[lo + 1:hi + 1]
        is_max = (c > left) & (c >= right)
        is_max &= c > s.floor_db[lo:hi] + db_above_floor
        idx = np.nonzero(is_max)[0] + lo
        if idx.size == 0:
            return Peaks(*(np.zeros(0) for _ in range(4)))

        idx = idx[db[idx] > db[idx].max() - dyn_range_db]

        # Reject Hann side lobes: a much weaker maximum right next to a strong peak
        # (side lobes sit >= 31 dB down within a few bins of the main lobe).
        keep = np.ones(idx.size, bool)
        span = int(np.ceil(8 * self.nfft / self.n))   # ~8 original bins
        for i, k in enumerate(idx):
            near = idx[np.abs(idx - k) <= span]
            if db[near].max() - db[k] > 25:
                keep[i] = False
        idx = idx[keep]

        if idx.size > max_peaks:
            idx = np.sort(idx[np.argsort(db[idx])[-max_peaks:]])

        # Parabolic interpolation through the three dB values around each maximum
        a, b, g = db[idx - 1], db[idx], db[idx + 1]
        denom = a - 2 * b + g
        p = np.where(np.abs(denom) > EPS, 0.5 * (a - g) / np.where(denom == 0, 1, denom), 0.0)
        p = np.clip(p, -0.5, 0.5)
        freq = (idx + p) * s.df
        pdb = b - 0.25 * (a - g) * p
        return Peaks(freq, pdb, 10 ** (pdb / 20), pdb - s.floor_db[idx])
