"""Terminal guitar tuner / chord detector.

The signal processing lives in the dsp package (shared with the web demo):
  Hann window -> FFT -> peak picking -> HPS pitch + octave check (tuner)
                                     -> harmonic summation multi-pitch + chroma templates (chords)

Usage:  .venv\\Scripts\\python cie2.py [--tuner] [--device ID]
For the browser UI run:  .venv\\Scripts\\python -m server
"""
import argparse
import time

from dsp import Analyzer, Config
from server.sources import MicSource


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tuner", action="store_true", help="single-note tuner output instead of chords")
    p.add_argument("--device", type=int, default=None, help="input device id")
    args = p.parse_args()

    mic = MicSource(args.device)
    cfg = Config(fs=mic.fs)
    an = Analyzer(cfg)
    print(f"Listening on '{mic.name}' at {mic.fs} Hz... stay quiet for 1 s (noise calibration). Ctrl+C to stop.")
    time.sleep(cfg.win_sec)                   # let the buffer fill once

    try:
        next_t = time.monotonic()
        while True:
            next_t += cfg.hop_sec
            time.sleep(max(0.0, next_t - time.monotonic()))
            r = an.process(mic.window(cfg.n_win))

            if r["calibrating"]:
                line = f"  calibrating... (level {r['level_db']:.0f} dBFS)"
            elif not r["gate_open"] and not r["held"]:
                line = f"  ...quiet (level {r['level_db']:.0f} dBFS, gate {r['gate_db']:.0f})"
            elif args.tuner:
                t = r["tuner"]
                line = (f"{t['note']:<4} {t['f0']:7.2f} Hz  {t['cents']:+6.1f} cents  "
                        f"(string {t['string']} {t['string_cents']:+.0f}c)") if t else "  ..."
            else:
                c = r["chord"]
                notes = " ".join(n["name"] for n in r["notes"])
                line = f"{c['name']:<8} [{notes}]  score {c['score']:.2f}" if c else "  ..."
            print(f"{line:<70}", end="\r")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        mic.close()


if __name__ == "__main__":
    main()
