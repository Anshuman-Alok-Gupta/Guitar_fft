"""Monophonic pitch: Harmonic Product Spectrum + octave check + harmonic refinement.

This is the refined version of cie2.detect_pitch().
"""
import numpy as np

from .notes import describe, nearest_string
from .spectrum import EPS, Peaks, Spectrum


def _maxfilt(x: np.ndarray, half: int) -> np.ndarray:
    """Running maximum over +-half bins (keeps harmonics that fall between bins)."""
    out = x.copy()
    for s in range(1, half + 1):
        out[:-s] = np.maximum(out[:-s], x[s:])
        out[s:] = np.maximum(out[s:], x[:-s])
    return out


def harmonic_product_spectrum(s: Spectrum, n_harm: int):
    """HPS as a *sum of logs* (same argmax as the product, but no dynamic-range blow-up).
    Returns (freqs, hps) over the first len/n_harm bins."""
    ref = s.mag.max() + EPS
    logm = np.log(s.mag + 1e-3 * ref)       # floor: a missing harmonic costs a bounded penalty
    L = len(logm) // n_harm
    hps = logm[:L].copy()
    for h in range(2, n_harm + 1):
        hps += _maxfilt(logm, h // 2)[::h][:L]
    return s.freqs[:L], hps


def _match(peaks: Peaks, target: float, tol_cents: float):
    """Index of the strongest peak within +-tol cents of target, or -1."""
    if peaks.freq.size == 0 or target <= 0:
        return -1
    cents = np.abs(1200 * np.log2(peaks.freq / target))
    ok = np.nonzero(cents < tol_cents)[0]
    return int(ok[np.argmax(peaks.amp[ok])]) if ok.size else -1


def _has(peaks, target, tol=50.0, min_above_floor=6.0):
    i = _match(peaks, target, tol)
    return i >= 0 and peaks.above_floor[i] >= min_above_floor


def _octave_correct(f0: float, peaks: Peaks, fmin: float, fmax: float) -> float:
    # Too high? HPS can land on any multiple k*f0 when the spectrum is rich in harmonics.
    # Test f0/k, lowest first: if the in-between harmonics (f0/k * j, j < k) really exist,
    # f0 was only a partial -- a single note never has partials between its harmonics.
    for k in range(8, 1, -1):
        sub = f0 / k
        if sub < fmin:
            continue
        between = [j for j in range(1, 2 * k) if j % k]      # skip multiples of the old f0
        found = [_has(peaks, j * sub) for j in between]
        # the fundamental itself, or (low notes, weak in small mics) the 2nd and 3rd harmonic
        fund_ok = found[0] or (sub < 165 and _has(peaks, 2 * sub) and _has(peaks, 3 * sub))
        if fund_ok and sum(found) >= 0.75 * len(found):
            f0 = sub
            break
    # Too low? If none of the odd harmonics (1, 3, 5) of f0 exist but 2*f0 does,
    # HPS latched onto a sub-harmonic.
    for _ in range(2):
        if 2 * f0 > fmax:
            break
        if not any(_has(peaks, k * f0) for k in (1, 3, 5)) and _has(peaks, 2 * f0):
            f0 = 2 * f0
        else:
            break
    return f0


def _refine(f0: float, peaks: Peaks, n_harm: int = 6, tol_cents: float = 40.0) -> float:
    """Amplitude-weighted average of f_h / h over the matched harmonics (sub-cent accurate)."""
    est, w = [], []
    for h in range(1, n_harm + 1):
        i = _match(peaks, h * f0, tol_cents)
        if i >= 0:
            est.append(peaks.freq[i] / h)
            w.append(peaks.amp[i])
    return float(np.average(est, weights=w)) if est else f0


def _confidence(f0: float, peaks: Peaks, fmax_peaks: float) -> float:
    """Share of the peak energy that is explained by harmonics of f0."""
    if peaks.freq.size == 0:
        return 0.0
    used = np.zeros(peaks.freq.size, bool)
    for h in range(1, int(fmax_peaks / f0) + 1):
        i = _match(peaks, h * f0, 40.0)
        if i >= 0:
            used[i] = True
    e = peaks.amp ** 2
    return float(e[used].sum() / (e.sum() + EPS))


def detect_pitch(s: Spectrum, peaks: Peaks, cfg, hps_result=None):
    """Return a dict describing the single strongest pitch, or None."""
    if peaks.freq.size == 0:
        return None
    fh, hps = hps_result if hps_result is not None else harmonic_product_spectrum(s, cfg.hps_harmonics)
    valid = (fh >= cfg.fmin) & (fh <= cfg.fmax)
    if not valid.any():
        return None
    k = int(np.argmax(np.where(valid, hps, -np.inf)))
    f0 = float(fh[k])

    f0 = _octave_correct(f0, peaks, cfg.fmin, cfg.fmax)
    # a plucked string is never a lone sinusoid (hum, feedback, a whistle): need 2+ harmonics
    if sum(_has(peaks, h * f0, 40.0) for h in range(1, 7)) < 2:
        return None
    f0 = _refine(f0, peaks)

    d = describe(f0, cfg.a4)
    if d is None:
        return None
    midi, name, cents = d
    string, string_cents = nearest_string(f0, cfg.a4)
    return {
        "f0": f0,
        "midi": midi,
        "note": name,
        "cents": cents,
        "string": string,
        "string_cents": string_cents,
        "confidence": _confidence(f0, peaks, cfg.peak_fmax),
    }
