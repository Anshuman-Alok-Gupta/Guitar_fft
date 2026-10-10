"""Write synthetic guitar WAVs into recordings/ (for testing the UI without a guitar).

Usage:  .venv\\Scripts\\python make_samples.py
"""
from pathlib import Path

import numpy as np

from dsp import synth

FS = 48000
OUT = Path(__file__).resolve().parent / "recordings"


def main():
    OUT.mkdir(exist_ok=True)
    gap = np.zeros(int(0.3 * FS))

    # open strings one after another (tuner demo)
    parts = []
    for m in synth.OPEN_STRINGS:
        parts += [synth.note(m, 1.6, FS), gap]
    synth.write_wav(OUT / "synth-open-strings.wav", synth.add_noise(np.concatenate(parts), 35), FS)

    # a chord progression (chord demo)
    parts = []
    for i, name in enumerate(["G", "C", "D", "Em", "Am", "F", "E", "A"]):
        parts += [synth.strum(name, 2.2, FS, seed=i), gap]
    synth.write_wav(OUT / "synth-progression.wav", synth.add_noise(np.concatenate(parts), 35), FS)

    for name in ["E", "A", "D", "G", "C", "Am", "Em"]:
        synth.write_wav(OUT / f"synth-chord-{name}.wav", synth.add_noise(synth.strum(name, 3.0, FS), 35), FS)
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("synth-*.wav"))))


if __name__ == "__main__":
    main()
