from dataclasses import dataclass


@dataclass
class Config:
    """All tunable parameters of the analysis chain in one place."""

    fs: int = 48000            # sample rate (overwritten with the mic's native rate)
    win_sec: float = 0.37      # analysis window: ~2.7 Hz bins, enough to split E2/F2 after interpolation
    hop_sec: float = 0.05      # new result every 50 ms -> 20 UI updates per second
    a4: float = 440.0          # tuning reference

    # Fundamental search range: E2 = 82.4 Hz (slack for drop tuning) up to a 24-fret high E
    fmin: float = 75.0
    fmax: float = 1400.0

    # Spectral peak picking
    peak_fmin: float = 70.0    # also skips 50/60 Hz mains hum
    peak_fmax: float = 4000.0
    peak_db_above_floor: float = 10.0
    peak_dynamic_range_db: float = 60.0   # ignore peaks this far below the strongest one
    max_peaks: int = 60

    # Monophonic pitch (HPS)
    hps_harmonics: int = 5

    # Polyphonic pitch (iterative harmonic summation)
    max_notes: int = 6                # six strings
    midi_lo: int = 40                 # E2
    midi_hi: int = 88                 # E6
    mp_harmonics: int = 8
    mp_tolerance_cents: float = 40.0
    mp_decay: float = 0.8             # harmonic weight w_h = decay**(h-1)
    mp_min_rel_salience: float = 0.2  # stop when a note is weaker than this x the first note
    mp_anchor_range_db: float = 35.0  # a note's anchor peak must be within this of the loudest peak
    mp_anchor_above_floor_db: float = 16.0  # ...and this far above the local noise floor

    # Chord matching
    chroma_fmin: float = 75.0
    chroma_fmax: float = 1300.0
    chord_min_score: float = 0.6

    # Gate / tracking
    gate_db_above_noise: float = 12.0   # gate opens this far above the calibrated noise floor
    gate_hysteresis_db: float = 4.0     # ...and closes this much lower
    gate_min_db: float = -65.0          # never open below this absolute level (dBFS)
    calibrate_sec: float = 1.0
    smooth_frames: int = 5
    hold_sec: float = 1.5
    onset_skip_sec: float = 0.06

    @property
    def n_win(self) -> int:
        return int(round(self.win_sec * self.fs))

    @property
    def n_hop(self) -> int:
        return int(round(self.hop_sec * self.fs))
