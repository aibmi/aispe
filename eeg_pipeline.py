import time
import sys
import threading
import numpy as np
from config import MI_POWER_THRESHOLD, MI_LATERALIZATION_DELTA, MI_SAMPLING_WINDOW_SEC, MI_REFRACTORY_SEC

try:
    import brainflow
    from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
    from brainflow.data_filter import DataFilter, FilterTypes
    HAS_BRAINFLOW = True
except ImportError:
    HAS_BRAINFLOW = False


class BrainFlowEEGPipeline:
    def __init__(self, use_synthetic=True, sampling_window_sec=MI_SAMPLING_WINDOW_SEC):
        self.running = True
        self.board = None
        self.use_synthetic = use_synthetic
        self.sampling_window_sec = sampling_window_sec

        self.eeg_pulse_event = threading.Event()
        self.connection_lost = threading.Event()
        self.on_disconnect = None  # optional callable(reason: str)

        if not HAS_BRAINFLOW or use_synthetic:
            self.board_id = -1
        else:
            self.board_id = 1

    def initialize_eeg_stream(self):
        if not HAS_BRAINFLOW:
            return True  # synthetic fallback, not a hardware failure

        params = BrainFlowInputParams()
        try:
            self.board = BoardShim(self.board_id, params)
            self.board.prepare_session()
            self.board.start_stream()
            return True
        except Exception as e:
            self._report_disconnect(f"EEG board init failed: {e}")
            return False

    def _report_disconnect(self, reason):
        self.connection_lost.set()
        if self.on_disconnect:
            try:
                self.on_disconnect(reason)
            except Exception:
                pass

    def is_hardware_connected(self):
        if self.use_synthetic or not HAS_BRAINFLOW:
            return True  # simulation mode is never "disconnected"
        return self.board is not None and not self.connection_lost.is_set()

    def _eeg_processing_worker(self):
        if not self.board:
            self._run_zero_library_simulation()
            return

        try:
            sampling_rate = BoardShim.get_sampling_rate(self.board_id)
            window_size = int(sampling_rate * self.sampling_window_sec)
            eeg_channels = BoardShim.get_eeg_channels(self.board_id)
        except Exception as e:
            self._report_disconnect(f"EEG metadata read failed: {e}")
            return

        two_channel = len(eeg_channels) >= 2
        c3_idx = eeg_channels[0]
        c4_idx = eeg_channels[1] if two_channel else None

        if two_channel:
            print("🧠 [MI PIPELINE]: C4 channel detected — using C3/C4 lateralization index.")
        else:
            print("⚠️ [MI PIPELINE]: Only one EEG channel found — falling back to single-channel "
                  "C3 threshold. Wire C4 to a second Ganglion input for the more robust mode.")

        baseline = None            # baseline_index (2-channel) or baseline_power (1-channel fallback)
        calibration_samples = 0

        while self.running:
            try:
                data = self.board.get_current_board_data(window_size)
            except Exception as e:
                self._report_disconnect(f"EEG stream read failed: {e}")
                return

            if data.shape[1] < window_size:
                time.sleep(0.05)
                continue

            c3_signal = data[c3_idx]
            DataFilter.perform_bandpass(c3_signal, sampling_rate, 19.0, 11.0, 4, FilterTypes.BUTTERWORTH.value, 0.0)
            c3_power = np.var(c3_signal)

            if two_channel:
                c4_signal = data[c4_idx]
                DataFilter.perform_bandpass(c4_signal, sampling_rate, 19.0, 11.0, 4, FilterTypes.BUTTERWORTH.value, 0.0)
                c4_power = np.var(c4_signal)
                # Lateralization index: rises when C3 desyncs relative to C4 (right-hand imagery).
                # Dividing by the sum, not just C3, cancels out artifacts that hit both channels equally.
                current_value = (c4_power - c3_power) / (c4_power + c3_power + 1e-9)
            else:
                current_value = c3_power

            if baseline is None or calibration_samples < 30:
                if baseline is None:
                    baseline = current_value
                else:
                    baseline = (baseline * 0.9) + (current_value * 0.1)
                calibration_samples += 1
                time.sleep(0.1)
                continue

            if two_channel:
                triggered = current_value > (baseline + MI_LATERALIZATION_DELTA)
            else:
                triggered = current_value < (baseline * MI_POWER_THRESHOLD)

            if triggered:
                self.eeg_pulse_event.set()
                time.sleep(MI_REFRACTORY_SEC)

            time.sleep(0.05)

    def _run_zero_library_simulation(self):
        import keyboard
        while self.running:
            if keyboard.is_pressed('space'):
                self.eeg_pulse_event.set()
                time.sleep(0.4)
            time.sleep(0.01)

    def start_pipeline(self):
        self.initialize_eeg_stream()
        threading.Thread(target=self._eeg_processing_worker, daemon=True).start()

    def wait_for_eeg_action(self, scan_window_timeout):
        self.eeg_pulse_event.clear()
        activated = self.eeg_pulse_event.wait(timeout=scan_window_timeout)
        if activated:
            self.eeg_pulse_event.clear()
            return True
        return False

    def shutdown_pipeline(self):
        self.running = False
        if self.board and HAS_BRAINFLOW:
            try:
                if self.board.is_prepared():
                    self.board.stop_stream()
                    self.board.release_session()
            except Exception:
                pass
