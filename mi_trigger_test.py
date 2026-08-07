"""
mi_trigger_test.py — standalone MI (motor imagery) trigger prototype

Independent from aispe.py on purpose, same reasoning as the aispe2 audio
rewrite: build and prove the detection logic against FAKE data first, where
every trigger (or missed trigger) can be checked against ground truth,
before ever touching real hardware or real skin.

What this contains:
  1. SyntheticEEGSource — generates fake C3/C4 signal windows. Mostly resting
     baseline noise, with occasional injected "motor imagery" events (a
     relative power drop in C3 vs C4 — the pattern we're trying to detect).
  2. MIDetector — the actual C3/C4 lateralization detection logic, same
     design discussed for the real system: rolling baseline, lateralization
     index, threshold trigger, refractory period.
  3. A test harness that runs the detector against the synthetic source and
     prints whether each detection was correct — so the logic can be judged
     against a known answer, not against guesswork.

When real hardware arrives: only SyntheticEEGSource gets replaced with a
real BrainFlow data stream. MIDetector and everything downstream is meant
to stay exactly as-is.

Run: python mi_trigger_test.py
(Needs only Python's standard library + random — no extra installs.)
"""

import random
import time

# --- Detection constants (same names/roles as the config.py versions) ---
MI_LATERALIZATION_DELTA = 0.15   # trigger when the index rises this far above its own baseline
MI_REFRACTORY_SEC = 1.5          # ignore new triggers for this long right after a detected pulse
BASELINE_SMOOTHING = 0.9         # how much weight the old baseline keeps each update (0-1)
CALIBRATION_SAMPLES = 30         # samples used to establish the initial baseline


class SyntheticEEGSource:
    """Generates fake C3/C4 power readings. Call next_sample() repeatedly, same
    shape as reading real windows off a BrainFlow stream — this is the only
    piece that gets swapped out once real hardware is connected."""

    def __init__(self, event_probability=0.03, seed=None):
        self.event_probability = event_probability  # chance any given sample is a real MI event
        self.rng = random.Random(seed)
        self._event_remaining = 0  # samples left in an ongoing simulated event

    def next_sample(self):
        """Returns (c3_power, c4_power, was_real_event: bool) — the bool is
        ONLY for grading detector accuracy in this test; real hardware has no
        such ground truth, obviously."""
        baseline_power = 100.0
        noise = lambda: self.rng.uniform(-8, 8)

        if self._event_remaining > 0:
            self._event_remaining -= 1
            c3 = baseline_power * 0.55 + noise()   # C3 desyncs — power drops
            c4 = baseline_power + noise()
            return c3, c4, True

        if self.rng.random() < self.event_probability:
            self._event_remaining = self.rng.randint(3, 6)  # event lasts a few samples
            c3 = baseline_power * 0.55 + noise()
            c4 = baseline_power + noise()
            return c3, c4, True

        c3 = baseline_power + noise()
        c4 = baseline_power + noise()
        return c3, c4, False


class MIDetector:
    """C3/C4 lateralization detector — same design as the real eeg_pipeline.py plan.
    Feed it (c3_power, c4_power) pairs one at a time via update()."""

    def __init__(self):
        self.baseline_index = None
        self._calibration_count = 0
        self._refractory_until = 0.0

    def update(self, c3_power, c4_power, now=None):
        """Returns True exactly on the sample that triggers a pulse, else False."""
        now = time.time() if now is None else now
        index = (c4_power - c3_power) / (c4_power + c3_power + 1e-9)

        if self.baseline_index is None or self._calibration_count < CALIBRATION_SAMPLES:
            if self.baseline_index is None:
                self.baseline_index = index
            else:
                self.baseline_index = (self.baseline_index * BASELINE_SMOOTHING) + (index * (1 - BASELINE_SMOOTHING))
            self._calibration_count += 1
            return False

        if now < self._refractory_until:
            return False

        if index > (self.baseline_index + MI_LATERALIZATION_DELTA):
            self._refractory_until = now + MI_REFRACTORY_SEC
            return True

        return False


def run_test(num_samples=400):
    source = SyntheticEEGSource(event_probability=0.03, seed=42)
    detector = MIDetector()

    true_positives = 0
    false_positives = 0
    missed_events = 0
    event_active = False

    print(f"Running {num_samples} synthetic samples through the detector...\n")

    for i in range(num_samples):
        c3, c4, was_real_event = source.next_sample()
        triggered = detector.update(c3, c4, now=i * 0.05)  # simulate ~20 samples/sec

        if was_real_event and not event_active:
            event_active = True
        if not was_real_event:
            event_active = False

        if triggered:
            if was_real_event:
                true_positives += 1
                print(f"  [{i:4d}] ✅ correctly triggered on a real event")
            else:
                false_positives += 1
                print(f"  [{i:4d}] ⚠️  triggered but NO real event was happening (false positive)")

    print(f"\n--- Results ---")
    print(f"True positives (correct detections): {true_positives}")
    print(f"False positives (wrong detections):  {false_positives}")
    print("\nNote: this run doesn't separately count missed real events yet — a real")
    print("accuracy pass would also track how many injected events produced NO trigger.")


if __name__ == "__main__":
    run_test()
    input("\nPress Enter to close this window...")
