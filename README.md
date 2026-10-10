# FFT Guitar Detector

Live guitar **note and chord** recognition with classical signal processing only (no machine learning).
A Python backend analyses the microphone. A browser page shows the spectrum, the detected notes and the chord name.

## Run it

Requires Python 3.10 or newer.

```powershell
git clone https://github.com/Anshuman-Alok-Gupta/Guitar_fft.git
cd Guitar_fft
python -m venv .venv                              # once
.venv\Scripts\pip install -r requirements.txt     # once
.venv\Scripts\python -m server                    # opens http://127.0.0.1:8000
```

Run locally, it listens to your computer's microphone straight away. Under Settings → Input device you can also switch to **This browser** mics.

**Online version:** https://dsp-cie-production.up.railway.app. The cloud server has no microphone, so press **🎤 Enable mic** and allow access. The browser then streams raw mic audio (with echo cancellation, noise suppression and AGC off) to the server over the WebSocket. Each browser tab gets its own session. Redeploy with `railway up -s dsp-cie` (the start command is in `railpack.json`).

Options:
- `--device ID` picks a server input device. The list is in Settings or at `/api/devices`.
- `--port 8000` sets the port.
- `--no-browser` starts the server without opening a browser.

Terminal-only version (no browser): `.venv\Scripts\python cie2.py` for chords, or `cie2.py --tuner`.

Tests run without a guitar or microphone: `.venv\Scripts\python -m pytest tests -q`

To get demo WAVs without a guitar, run `.venv\Scripts\python make_samples.py`. It writes them to `recordings\`, and they then appear under Settings → Recordings.

## How it works (`dsp\`)

| Stage | File | What it does |
|---|---|---|
| Window + FFT | `spectrum.py` | Takes 0.37 s of audio, removes DC, applies a Hann window, zero-pads 2×, then runs an rFFT to get magnitude in dB. |
| Noise floor + peaks | `spectrum.py` | Estimates the floor as the 30th percentile per octave band. Keeps local maxima at least 10 dB above it and rejects window side lobes. Parabolic interpolation gives sub-bin frequencies. |
| Tuner (one note) | `pitch.py` | Computes the Harmonic Product Spectrum as a sum of log magnitudes. A subharmonic check (f0/k, k = 2..8) fixes octave errors. f0 is then refined from the harmonics, which is accurate to about 1 cent. |
| Notes (polyphonic) | `multipitch.py` | Iterative harmonic summation finds up to 6 notes. Each candidate is anchored on a real peak, and spectral-smoothness subtraction handles shared partials. Ghost notes (a partial of a note already found) are rejected. |
| Chord | `chord.py` | Builds a 12-bin chroma and matches it by cosine similarity against 120 templates (12 roots × maj, min, 5, 7, maj7, m7, sus2, sus4, dim, aug). The templates include overtones. The score also uses the detected notes and a bass-note bonus. |
| Tracking | `tracker.py` | Calibrated noise gate with hysteresis, spectral-flux onset detection, a 5-frame median or vote, and a 1.5 s hold. |

What changed from the original `cie2.py`:
- **Missing dependency:** `sounddevice` is now installed.
- **Octave errors:** the octave and subharmonic correction fixes them.
- **Frequency precision:** f0 was snapped to the bin grid with an 8× zero-padded 262k-point FFT. It now uses 2× padding with interpolation.
- **Memory churn:** a ring buffer replaces the per-callback `np.roll` allocation.
- **Fixed noise gate:** replaced by an adaptive gate with a Calibrate button.
- **Polyphony:** chords were not supported and now are.
- **Flicker:** onset detection, smoothing and hold stop the readout jumping.
- **`f0 = 0` crash:** now guarded.

## Demo-day checklist

1. **Windows mic settings.** Go to Settings → System → Sound → your microphone and turn off *Audio enhancements*, *Noise suppression* and any AGC. These features cut sustained notes.
2. **Placement.** Put the laptop mic 20–30 cm from the sound hole. A USB audio interface or pickup is better; select it under Settings → Input device.
3. **Calibrate.** Start the server, keep the room quiet, and press **Calibrate** (or **C**). The level meter shows the gate marker.
4. **Tune the guitar.** Use **Tuner** mode (**T**) and pluck each open string until the needle shows "✓ in tune".
5. **Play.** Switch to **Chord** mode and strum one chord at a time. Once a chord has held for 0.3 s it is captured and stays on screen, along with its notes, chroma and spectrum (the white line), until you play a different chord. It shows as "Last chord" after the sound fades. Press **Space** to freeze the display while you explain a spectrum.
6. **Fallback.** At rehearsal, open Settings and press **Record 5 s** after each chord to save WAVs into `recordings\`. If the room is too noisy on the day, play those from Settings → Recordings or with **Upload WAV**.
7. **Screen.** On a laptop the default layout fits a 1366×768 screen. For a projector or an audience looking over your shoulder, press **Present** (or **P**) for larger text. On a projector, also switch to the light theme (Settings → Toggle light / dark), because projectors wash out dark backgrounds.

Keyboard: **Space** freeze · **C** calibrate · **T** toggle tuner/chord · **P** present mode.

## Limits worth knowing (and explaining in a viva)
- **Octave doublings are merged.** E2 and E3 in an open E chord show as one note per pitch class: a note at exactly 2× another is indistinguishable from that note's 2nd harmonic. The chord name is unaffected.
- **Detection needs a few strings.** Very short staccato strums and heavily muted chords give too few peaks to be reliable.
- **Chord vocabulary.** Chords outside the 10 template types (e.g. add9, 6, 13) are named by their closest match.
