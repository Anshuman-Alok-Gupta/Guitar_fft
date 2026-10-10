"""DSP tests on synthetic guitar signals (no guitar or microphone needed).

Run:  .venv\\Scripts\\python -m pytest tests -q
"""
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dsp import Analyzer, Config, synth                     # noqa: E402
from dsp.notes import describe, midi_to_name, NOTE_NAMES     # noqa: E402

FS = 48000
LEAD_IN = 2.0          # silence for noise calibration (+ one analysis window)


def run(x, fs=FS, a4=440.0, start=0.45, stop=1.3, noise=1e-4):
    """Feed x (after a silent lead-in) through the analyzer hop by hop, the way the
    live server does, and return the results between start..stop s after the pluck."""
    cfg = Config(fs=fs, a4=a4)
    an = Analyzer(cfg)
    rng = np.random.default_rng(5)
    sig = np.concatenate([np.zeros(int(LEAD_IN * fs)), 0.3 * x])
    sig += rng.normal(0, noise, len(sig))
    out = []
    for end in range(cfg.n_win, len(sig), cfg.n_hop):
        r = an.process(sig[end - cfg.n_win:end], t=end / fs)
        if LEAD_IN + start < end / fs < LEAD_IN + stop:
            out.append(r)
    return out


def majority(values):
    return Counter(values).most_common(1)[0][0]


def tuner_note(results):
    return majority(r["tuner"]["note"] if r["tuner"] else None for r in results)


def chord_name(results):
    """Majority chord label, ignoring any inversion suffix (C/E -> C)."""
    return majority(r["chord"]["name"].split("/")[0] if r["chord"] else None for r in results)


# ---------------------------------------------------------------- notes / tuner
@pytest.mark.parametrize("string", synth.OPEN_STRINGS)
@pytest.mark.parametrize("fret", [0, 1, 3, 5, 7, 9, 12])
def test_single_note(string, fret):
    m = string + fret
    rs = run(synth.add_noise(synth.note(m, 2.0, FS), 30))
    assert tuner_note(rs) == midi_to_name(m)
    cents = np.median([r["tuner"]["cents"] for r in rs if r["tuner"]])
    assert abs(cents) < 5


@pytest.mark.parametrize("midi", [40, 45, 59])                # E2, A2, B3
def test_no_octave_error_with_weak_fundamental(midi):
    """Laptop mics barely pick up the lowest partial; HPS alone tends to jump an octave."""
    rs = run(synth.add_noise(synth.note(midi, 2.0, FS, fund_gain=0.15), 30))
    assert tuner_note(rs) == midi_to_name(midi)


@pytest.mark.parametrize("cents_off", [-30, -12, 7, 25])
def test_tuner_reads_detuned_strings(cents_off):
    f = 110.0 * 2 ** (cents_off / 1200)
    rs = run(synth.add_noise(synth.pluck(f, 2.0, FS), 30))
    readings = [r["tuner"]["cents"] for r in rs if r["tuner"]]
    assert tuner_note(rs) == "A2"
    assert abs(np.median(readings) - cents_off) < 3


def test_karplus_strong_notes():
    for m in (40, 47, 52, 57, 64, 69):
        rs = run(synth.note(m, 2.0, FS, model="ks"))
        assert tuner_note(rs) == midi_to_name(m)


def test_other_sample_rate_and_reference():
    rs = run(synth.note(57, 2.0, 44100, a4=432.0), fs=44100, a4=432.0)
    assert tuner_note(rs) == "A3"
    assert abs(np.median([r["tuner"]["cents"] for r in rs if r["tuner"]])) < 5


def test_describe_rejects_invalid():
    assert describe(0) is None and describe(float("nan")) is None and describe(-5) is None


# ---------------------------------------------------------------- chords
CHORDS = ["E", "A", "D", "G", "C", "Am", "Em", "Dm", "F", "E5", "A7"]


@pytest.mark.parametrize("model", ["pluck", "ks"])
@pytest.mark.parametrize("name", CHORDS)
def test_chord_name(name, model):
    rs = run(synth.add_noise(synth.strum(name, 2.0, FS, model=model), 30))
    assert chord_name(rs) == name


@pytest.mark.parametrize("name", CHORDS)
def test_chord_notes_are_chord_tones(name):
    """Every detected pitch class is a chord tone, and every chord tone is found."""
    rs = run(synth.add_noise(synth.strum(name, 2.0, FS, weak_bass=True), 30))
    expected = {m % 12 for m in synth.chord_midis(name)}
    found = Counter(frozenset(n["midi"] % 12 for n in r["notes"]) for r in rs).most_common(1)[0][0]
    assert found == expected, (sorted(NOTE_NAMES[p] for p in found), sorted(NOTE_NAMES[p] for p in expected))
    bass = majority(r["notes"][0]["midi"] for r in rs if r["notes"])
    assert bass == min(synth.chord_midis(name))


@pytest.mark.parametrize("name", ["G", "C", "D", "Am"])
def test_no_stray_notes_while_chord_rings(name):
    """Every frame of a ringing chord: no note outside the chord (noise must not
    assemble phantom notes out of small ripples far below the partials)."""
    for seed in range(3):
        x = synth.add_noise(synth.strum(name, 3.0, FS, seed=seed), 35, seed=seed)
        rs = run(x, start=0.4, stop=2.6)
        tones = {m % 12 for m in synth.chord_midis(name)}
        stray = [n["name"] for r in rs for n in r["notes"] if n["midi"] % 12 not in tones]
        assert not stray, (seed, stray)


@pytest.mark.parametrize("name", ["G", "C", "Am", "F"])
def test_chords_in_noise(name):
    rs = run(synth.add_noise(synth.strum(name, 2.0, FS, seed=3), 15))
    assert chord_name(rs) == name


@pytest.mark.parametrize("name", ["D", "Em"])
def test_out_of_tune_guitar(name):
    """Whole guitar 20 cents sharp: still the same chord."""
    rs = run(synth.add_noise(synth.strum(name, 2.0, FS), 30), a4=440.0 * 2 ** (-20 / 1200))
    assert chord_name(rs) == name


# ---------------------------------------------------------------- gate / robustness
def test_silence_and_noise_keep_gate_closed():
    rs = run(np.zeros(2 * FS), noise=1e-3)
    assert not any(r["gate_open"] for r in rs)
    assert all(r["chord"] is None and r["tuner"] is None for r in rs)


def test_mains_hum_is_ignored():
    t = np.arange(2 * FS) / FS
    hum = np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 100 * t)
    rs = run(hum)
    assert all(not r["notes"] for r in rs)
    assert all(r["tuner"] is None for r in rs)


def test_chord_change_is_followed():
    a = synth.strum("G", 1.5, FS)
    b = synth.strum("C", 1.5, FS, seed=4)
    rs = run(np.concatenate([a, b]), start=1.5 + 0.5, stop=1.5 + 1.2)
    assert chord_name(rs) == "C"


def test_frame_is_fast_enough():
    cfg = Config(fs=FS)
    an = Analyzer(cfg)
    x = synth.strum("G", 1.0, FS)[:cfg.n_win]
    for _ in range(25):           # past calibration, gate open
        an.process(x)
    t = time.perf_counter()
    for _ in range(40):
        an.process(x)
    ms = (time.perf_counter() - t) / 40 * 1000
    assert ms < cfg.hop_sec * 1000 / 2, f"{ms:.1f} ms per frame"
