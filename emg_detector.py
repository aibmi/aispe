"""
emg_detector.py — EMG (muscle) detection logic + synthetic test source

Same shape as mi_detector.py, same reasoning: build and prove logic against
fake data first. Threshold below (2.5x baseline) is an untested first-pass
placeholder, same spirit as MI's original 0.15 — good enough to prove the
wiring works, meant to be refined once real signal (or the planned
visualizer) exists to tune against.

When real hardware arrives: only SyntheticEMGSource gets replaced with a
real BrainFlow data stream reading the bipolar EMG channel. EMGDetector
itself is meant to stay as-is.
"""

import random
import time

# --- Detection constants ---
EMG_TRIGGER_MULTIPLIER = 2.5     # trigger when the envelope exceeds this multiple of baseline
EMG_REFRACTORY_SEC = 1.5         # ignore new triggers for this long right after a detected pulse
ENVELOPE_SMOOTHING = 0.7         # how much weight the running envelope keeps each update (0-1)
BASELINE_SMOOTHING = 0.9         # how much weight the baseline keeps each update during calibration
CALIBRATION_SAMPLES = 30         # samples used to establish the initial resting baseline


class SyntheticEMGSource:
    """Generates fake raw EMG samples (microvolts). Mostly small resting noise,
    with occasional injected "contraction" bursts — much larger amplitude,
    a stronger/easier signal than MI's, matching how real EMG behaves."""

    def __init__(self, event_probability=0.003, seed=None):
        self.event_probability = event_probability
        self.rng = random.Random(seed)
        self._event_remaining = 0

    def next_sample(self):
        """Returns (raw_microvolts, was_real_event: bool) — the bool is ONLY for
        grading detector accuracy in tests; real hardware has no such ground truth."""
        if self._event_remaining > 0:
            self._event_remaining -= 1
            return self.rng.uniform(-80, 80), True  # contraction burst

        if self.rng.random() < self.event_probability:
            self._event_remaining = self.rng.randint(5, 15)  # burst lasts several samples
            return self.rng.uniform(-80, 80), True

        return self.rng.uniform(-5, 5), False  # resting muscle noise


class EMGDetector:
    """Rectify -> smooth (envelope) -> compare to calibrated resting baseline.
    Feed it raw samples one at a time via update()."""

    def __init__(self):
        self.envelope = None
        self.baseline_envelope = None
        self._calibration_count = 0
        self._refractory_until = 0.0

    def update(self, raw_sample, now=None):
        """Returns True exactly on the sample that triggers a pulse, else False."""
        now = time.time() if now is None else now
        rectified = abs(raw_sample)

        if self.envelope is None:
            self.envelope = rectified
        else:
            self.envelope = (self.envelope * ENVELOPE_SMOOTHING) + (rectified * (1 - ENVELOPE_SMOOTHING))

        if self.baseline_envelope is None or self._calibration_count < CALIBRATION_SAMPLES:
            if self.baseline_envelope is None:
                self.baseline_envelope = self.envelope
            else:
                self.baseline_envelope = (self.baseline_envelope * BASELINE_SMOOTHING) + (self.envelope * (1 - BASELINE_SMOOTHING))
            self._calibration_count += 1
            return False

        if now < self._refractory_until:
            return False

        if self.envelope > (self.baseline_envelope * EMG_TRIGGER_MULTIPLIER):
            self._refractory_until = now + EMG_REFRACTORY_SEC
            return True

        return False
