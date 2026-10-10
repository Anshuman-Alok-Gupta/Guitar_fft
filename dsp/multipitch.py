"""Polyphonic pitch: iterative harmonic summation with spectral-smoothness subtraction
(after A. Klapuri, "Multiple fundamental frequency estimation based on harmonicity
and spectral smoothness", 2003). Pure signal processing, no training data.

1. Every candidate note (E2..E6) is anchored on a real spectral peak: its fundamental
   (or, for low notes whose fundamental the mic barely picks up, its 2nd harmonic / 2).
2. Its harmonics are looked for at exact integer multiples of that *measured* frequency,
   so a slightly out-of-tune guitar still works and random peaks rarely fit.
3. Salience = sum_h w_h * amplitude of harmonic h. Take the most salient note.
4. Subtract the part of its partials explained by its own smooth spectral envelope, so a
   partial shared with another note (C3's 3rd harmonic is also G3's 2nd) is not consumed.
5. Repeat until six notes or the next note is too weak. A note whose fundamental is just
   a partial of an already detected note (an octave/twelfth "ghost") is not accepted.
"""
import numpy as np

from .notes import midi_to_freq, midi_to_name
from .spectrum import Peaks

ANCHOR_CENTS = 50.0          # fundamental must be within a quarter tone of the candidate
WEAK_FUND_MIDI = 52          # below E3 the fundamental may be missing in a laptop mic


def _strongest_near(freq, val, targets, tol_cents):
    """For each target, index of the strongest peak within +-tol cents, or -1 if none."""
    cents = 1200 * np.log2(freq[None, :] / targets[:, None])
    v = np.where(np.abs(cents) < tol_cents, val[None, :], 0.0)
    return np.where(v.max(axis=1) > 0, v.argmax(axis=1), -1)


def _prefer_subharmonic(c, sal, f_ref, ratio=0.6):
    """If the winner sits at k * (an anchored lower candidate), k = 2..5, and that lower
    note is nearly as salient, the winner is most likely a partial of the lower note
    (B3 = 3 x E2): take the lower one first, it will explain the winner's partials."""
    for _ in range(3):
        best = c
        for k in (2, 3, 4, 5):
            dev = np.abs(1200 * np.log2(f_ref * k / f_ref[c]))
            ok = np.nonzero(np.nan_to_num(dev, nan=1e9) < 30)[0]
            ok = ok[sal[ok] >= ratio * sal[c]]
            if ok.size:
                best = int(ok[np.argmax(sal[ok])])
                break
        if best == c:
            return c
        c = best
    return c


def detect_notes(peaks: Peaks, cfg):
    if peaks.freq.size == 0:
        return []

    mids = np.arange(cfg.midi_lo, cfg.midi_hi + 1)
    fc = midi_to_freq(mids, cfg.a4)
    H = cfg.mp_harmonics
    h = np.arange(1, H + 1)
    w = cfg.mp_decay ** (h - 1)
    tol = cfg.mp_tolerance_cents * 0.5 + 1.5 * h       # relative to the measured f0

    amp0 = np.sqrt(peaks.amp)          # mild compression: one loud partial must not dominate
    remaining = amp0.copy()
    used = np.zeros(peaks.freq.size, bool)   # peaks already explained by a detected note
    # A note must be anchored on a real partial, not on a noise ripple: noise bins exceed
    # the floor estimate by 10 dB a few % of the time, by 16 dB practically never.
    used |= peaks.db < peaks.db.max() - cfg.mp_anchor_range_db
    used |= peaks.above_floor < cfg.mp_anchor_above_floor_db
    chosen = np.zeros(len(mids), bool)
    notes, first = [], None

    for _ in range(cfg.max_notes):
        free = np.where(used, 0.0, remaining)
        # anchor: fundamental peak, else (low notes only) 2nd harmonic
        i1 = _strongest_near(peaks.freq, free, fc, ANCHOR_CENTS)
        i2 = _strongest_near(peaks.freq, free, 2 * fc, ANCHOR_CENTS)
        f_ref = np.where(i1 >= 0, peaks.freq[i1], np.nan)
        weak = (i1 < 0) & (i2 >= 0) & (mids < WEAK_FUND_MIDI)
        f_ref = np.where(weak, peaks.freq[i2] / 2, f_ref)

        targets = f_ref[:, None] * h[None, :]                          # (C, H)
        cents = 1200 * np.log2(peaks.freq[None, None, :] / targets[:, :, None])
        match = np.abs(cents) < tol[None, :, None]
        vals = np.where(match, remaining[None, None, :], 0.0)          # (C, H, P)
        best_idx = vals.argmax(axis=2)
        best = vals.max(axis=2) * (targets <= cfg.peak_fmax)
        best = np.nan_to_num(best)

        present = best > 0
        plausible = np.isfinite(f_ref) & (present[:, :6].sum(axis=1) >= 2)
        if weak.any():   # weak-fundamental notes need both the 2nd and 3rd harmonic
            plausible &= ~weak | (present[:, 1] & present[:, 2])
        sal = np.where(plausible & ~chosen, best @ w, 0.0)

        c = int(np.argmax(sal))
        if sal[c] <= 0:
            break
        c = _prefer_subharmonic(c, sal, f_ref)
        if first is None:
            first = sal[c]
        elif sal[c] < cfg.mp_min_rel_salience * first:
            break
        chosen[c] = True

        hs = np.nonzero(present[c])[0]
        pidx = best_idx[c, hs]
        freq = float(np.average(peaks.freq[pidx] / (hs + 1), weights=peaks.amp[pidx]))
        notes.append({
            "name": midi_to_name(mids[c]),
            "midi": int(mids[c]),
            "freq": freq,
            "salience": float(sal[c] / first),
            "harmonics": [float(f) for f in peaks.freq[pidx]],
        })

        # Spectral-smoothness subtraction + mark this note's partials as explained
        a = best[c]
        smooth = np.convolve(np.pad(a, 1, mode="edge"), np.ones(3) / 3, mode="valid")
        take = np.minimum(a, np.maximum(smooth, 0.5 * a))
        for hh in hs:
            p = best_idx[c, hh]
            remaining[p] = max(remaining[p] - take[hh], 0.0)
        # every partial of this note up to peak_fmax (not just the first H) is "explained":
        # no later note may be anchored on it
        f0 = f_ref[c]
        hk = np.round(peaks.freq / f0)
        dev = np.abs(1200 * np.log2(peaks.freq / (np.maximum(hk, 1) * f0)))
        used |= (hk >= 1) & (dev < cfg.mp_tolerance_cents * 0.5 + 1.5 * np.minimum(hk, 20))

    notes.sort(key=lambda n: n["midi"])
    return notes
