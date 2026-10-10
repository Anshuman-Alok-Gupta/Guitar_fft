"""Chord naming: chroma (pitch-class profile) + template matching.

The chroma folds every spectral peak onto 12 pitch classes. Each chord type is a
12-bin template that includes the overtones of its tones (2nd-4th harmonic, decaying),
because a real guitar string puts energy on the fifth above every note it plays.
The best template by cosine similarity names the chord.
"""
import numpy as np

from .notes import NOTE_NAMES, freq_to_midi
from .spectrum import Peaks

# suffix, long name, intervals (semitones above the root), prior (simple triads win ties)
CHORD_TYPES = [
    ("",     "major",      (0, 4, 7),     1.00),
    ("m",    "minor",      (0, 3, 7),     1.00),
    ("5",    "power",      (0, 7),        0.97),
    ("7",    "dominant 7", (0, 4, 7, 10), 0.97),
    ("maj7", "major 7",    (0, 4, 7, 11), 0.97),
    ("m7",   "minor 7",    (0, 3, 7, 10), 0.97),
    ("sus2", "sus2",       (0, 2, 7),     0.95),
    ("sus4", "sus4",       (0, 5, 7),     0.95),
    ("dim",  "diminished", (0, 3, 6),     0.95),
    ("aug",  "augmented",  (0, 4, 8),     0.95),
]

HARMONIC_SHIFTS = [(int(round(12 * np.log2(h))) % 12, 0.6 ** (h - 1)) for h in range(1, 5)]
BASS_BONUS = 0.04


def _template(intervals):
    t = np.zeros(12)
    for iv in intervals:
        for shift, w in HARMONIC_SHIFTS:
            t[(iv + shift) % 12] += w
    return t / np.linalg.norm(t)


def _plain_template(intervals):
    t = np.zeros(12)
    t[list(intervals)] = 1.0
    return t / np.linalg.norm(t)


# Matrices of all 12 roots x all chord types, plus their metadata.
# _TEMPLATES (with overtones) is matched against the raw-peak chroma,
# _PLAIN (chord tones only) against the chroma of the detected notes.
_TEMPLATES, _PLAIN, _META = [], [], []
for _suffix, _long, _ivs, _prior in CHORD_TYPES:
    _base, _plain = _template(_ivs), _plain_template(_ivs)
    for _root in range(12):
        _TEMPLATES.append(np.roll(_base, _root))
        _PLAIN.append(np.roll(_plain, _root))
        _META.append((_root, _suffix, _long, _ivs, _prior))
_TEMPLATES, _PLAIN = np.array(_TEMPLATES), np.array(_PLAIN)
_PRIORS = np.array([m[4] for m in _META])
_ROOTS = np.array([m[0] for m in _META])


def chroma(peaks: Peaks, cfg) -> np.ndarray:
    c = np.zeros(12)
    sel = (peaks.freq >= cfg.chroma_fmin) & (peaks.freq <= cfg.chroma_fmax)
    if not sel.any():
        return c
    f, a = peaks.freq[sel], peaks.amp[sel]
    m = freq_to_midi(f, cfg.a4)
    nearest = np.round(m)
    w = np.cos(np.pi * (m - nearest)) ** 2               # 1 on pitch, 0 at a quarter tone
    energy = np.log1p(100 * a / a.max())                  # log compression
    np.add.at(c, nearest.astype(int) % 12, w * energy)
    n = np.linalg.norm(c)
    return c / n if n > 0 else c


def notes_chroma(notes) -> np.ndarray:
    c = np.zeros(12)
    for n in notes:
        c[n["midi"] % 12] += n["salience"]
    nrm = np.linalg.norm(c)
    return c / nrm if nrm > 0 else c


def name_chord(chroma_vec: np.ndarray, notes, cfg):
    """Score = prior * (half peak-chroma match + half detected-notes match) + bass bonus.
    The two halves are independent evidence: raw spectrum vs. the multi-F0 result."""
    if not np.any(chroma_vec) or not notes:
        return None
    pcs = sorted({n["midi"] % 12 for n in notes})
    bass_pc = notes[0]["midi"] % 12

    if len(pcs) == 1:   # one pitch class (a single note, maybe in several octaves)
        return {"name": NOTE_NAMES[pcs[0]], "long": "single note", "root": NOTE_NAMES[pcs[0]],
                "score": 1.0, "tones": pcs, "bass": NOTE_NAMES[bass_pc], "alts": []}

    match = 0.5 * (_TEMPLATES @ chroma_vec) + 0.5 * (_PLAIN @ notes_chroma(notes))
    scores = match * _PRIORS + BASS_BONUS * (_ROOTS == bass_pc)
    order = np.argsort(scores)[::-1]
    best = order[0]
    root, suffix, long, ivs, _ = _META[best]
    alts = [{"name": NOTE_NAMES[_META[i][0]] + _META[i][1], "score": float(scores[i])}
            for i in order[:4]]
    if scores[best] < cfg.chord_min_score:
        return {"name": "N.C.", "long": "no chord", "root": None, "score": float(scores[best]),
                "tones": pcs, "bass": NOTE_NAMES[bass_pc], "alts": alts}
    name = NOTE_NAMES[root] + suffix
    if bass_pc != root and bass_pc in [(root + i) % 12 for i in ivs]:
        name += "/" + NOTE_NAMES[bass_pc]          # inversion, e.g. C/E
    return {
        "name": name,
        "long": f"{NOTE_NAMES[root]} {long}",
        "root": NOTE_NAMES[root],
        "score": float(scores[best]),
        "tones": [(root + i) % 12 for i in ivs],
        "bass": NOTE_NAMES[bass_pc],
        "alts": alts,
    }
