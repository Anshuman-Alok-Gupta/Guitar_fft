"""Synthetic guitar signals for testing without a guitar.

Two models:
- pluck(): additive plucked-string model (exact pitch, string stiffness, pluck position,
  faster decay for higher partials). Used where pitch accuracy is tested.
- karplus_strong(): the classic delay-line + averaging-filter string. Integer delay, so
  its pitch can be a few cents off; used as a second, independent "instrument".
"""
import wave

import numpy as np

from .notes import STANDARD_TUNING, midi_to_freq

OPEN_STRINGS = [m for _, m in STANDARD_TUNING]          # E2 A2 D3 G3 B3 E4

# Frets low E -> high e, None = string not played
CHORD_SHAPES = {
    "E":  [0, 2, 2, 1, 0, 0],
    "A":  [None, 0, 2, 2, 2, 0],
    "D":  [None, None, 0, 2, 3, 2],
    "G":  [3, 2, 0, 0, 0, 3],
    "C":  [None, 3, 2, 0, 1, 0],
    "Am": [None, 0, 2, 2, 1, 0],
    "Em": [0, 2, 2, 0, 0, 0],
    "Dm": [None, None, 0, 2, 3, 1],
    "F":  [1, 3, 3, 2, 1, 1],
    "E5": [0, 2, 2, None, None, None],
    "A7": [None, 0, 2, 0, 2, 0],
}


def pluck(freq, dur, fs, pluck_pos=0.18, inharm=5e-5, t60=3.0, fund_gain=1.0, rng=None):
    rng = rng or np.random.default_rng(0)
    t = np.arange(int(dur * fs)) / fs
    y = np.zeros_like(t)
    for h in range(1, 40):
        fh = h * freq * np.sqrt(1 + inharm * h * h)
        if fh > 0.45 * fs or fh > 8000:
            break
        a = abs(np.sin(np.pi * h * pluck_pos)) / h ** 1.5
        if h == 1:
            a *= fund_gain
        tau = t60 / 6.9 / (1 + 0.25 * (h - 1))
        y += a * np.exp(-t / tau) * np.sin(2 * np.pi * fh * t + rng.uniform(0, 2 * np.pi))
    y *= 1 - np.exp(-t / 0.002)                          # 2 ms attack
    return y / (np.abs(y).max() + 1e-12)


def karplus_strong(freq, dur, fs, decay=0.996, rng=None):
    rng = rng or np.random.default_rng(0)
    N = max(2, int(round(fs / freq - 0.5)))               # averaging filter adds half a sample
    n = int(dur * fs)
    y = np.zeros(n + N + 1)
    burst = rng.uniform(-1, 1, N + 1)
    y[:N + 1] = np.convolve(burst, [0.5, 0.5], mode="same")
    # y[k] = decay/2 * (y[k-N] + y[k-N-1]) only looks >= N samples back -> vectorise per block
    for s in range(N + 1, n + N + 1, N):
        e = min(s + N, n + N + 1)
        y[s:e] = 0.5 * decay * (y[s - N:e - N] + y[s - N - 1:e - N - 1])
    y = y[N + 1:]
    return y / (np.abs(y).max() + 1e-12)


def note(midi, dur=1.5, fs=48000, model="pluck", a4=440.0, **kw):
    f = float(midi_to_freq(midi, a4))
    return pluck(f, dur, fs, **kw) if model == "pluck" else karplus_strong(f, dur, fs, **kw)


def chord_midis(shape):
    frets = CHORD_SHAPES[shape] if isinstance(shape, str) else shape
    return [o + f for o, f in zip(OPEN_STRINGS, frets) if f is not None]


def strum(shape, dur=2.0, fs=48000, model="pluck", strum_ms=12, seed=0, weak_bass=False):
    """Down-strum low to high, each string a few ms after the previous one."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(dur * fs))
    for i, m in enumerate(chord_midis(shape)):
        kw = {"rng": rng}
        if model == "pluck":
            kw["pluck_pos"] = rng.uniform(0.12, 0.25)
            if weak_bass and m < 52:
                kw["fund_gain"] = 0.2                     # small speakers/mics lose the lowest partial
        y = note(m, dur, fs, model, **kw) * rng.uniform(0.7, 1.0)
        d = int(i * strum_ms * 1e-3 * fs)
        out[d:] += y[:len(out) - d]
    return out / np.abs(out).max()


def add_noise(x, snr_db=30, seed=1):
    rng = np.random.default_rng(seed)
    p = np.mean(x ** 2) / 10 ** (snr_db / 10)
    return x + rng.normal(0, np.sqrt(p), len(x))


def write_wav(path, x, fs):
    x = np.clip(np.asarray(x) * 0.9 / (np.abs(x).max() + 1e-12), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes((x * 32767).astype("<i2").tobytes())
