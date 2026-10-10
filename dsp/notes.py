import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Standard tuning, low to high: (name, MIDI number)
STANDARD_TUNING = [("E2", 40), ("A2", 45), ("D3", 50), ("G3", 55), ("B3", 59), ("E4", 64)]


def freq_to_midi(f, a4=440.0):
    """Fractional MIDI number (A4 = 69). Works on scalars and arrays."""
    return 69 + 12 * np.log2(np.asarray(f, dtype=float) / a4)


def midi_to_freq(m, a4=440.0):
    return a4 * 2 ** ((np.asarray(m, dtype=float) - 69) / 12)


def midi_to_name(m: int) -> str:
    m = int(m)
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def describe(f0, a4=440.0):
    """Return (midi, name, cents off the nearest note), or None for an invalid frequency."""
    if f0 is None or not np.isfinite(f0) or f0 <= 0:
        return None
    m = float(freq_to_midi(f0, a4))
    midi = int(round(m))
    return midi, midi_to_name(midi), 100.0 * (m - midi)


def nearest_string(f0, a4=440.0):
    """Closest open string in standard tuning: (name, cents away from it)."""
    m = float(freq_to_midi(f0, a4))
    name, midi = min(STANDARD_TUNING, key=lambda s: abs(s[1] - m))
    return name, 100.0 * (m - midi)
