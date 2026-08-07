"""
real_hardware_source.py — real OpenBCI Ganglion connection for MI + EMG

NOT YET WIRED INTO aispe.py. Built ready for when the headband arrives —
swapping it in is meant to be a small, one-line-per-source change (see the
bottom of this file for exactly what that change looks like).

Shares ONE physical board connection between MI and EMG, since both signals
come from the same real Ganglion board:
  - MI reads channels 1 and 2 (C3, C4)
  - EMG reads channel 3 (bipolar muscle signal)
This matters because opening two separate connections to the same physical
USB device at once would likely fail or conflict — RealEEGSource and
RealEMGSource both quietly share one GanglionBoard behind the scenes.

Same graceful-failure pattern as ps_detector.py: if the board isn't found —
not plugged in, brainflow not installed, wrong dongle — is_connected stays
False and samples come back as neutral zeros instead of crashing.

Install: pip install brainflow numpy
"""

try:
    from brainflow.board_shim import BoardShim, BrainFlowInputParams
    from brainflow.data_filter import DataFilter, FilterTypes
    import numpy as np
    HAS_BRAINFLOW = True
except ImportError:
    HAS_BRAINFLOW = False

GANGLION_BOARD_ID = 1  # BrainFlow's ID for the real OpenBCI Ganglion board


class GanglionBoard:
    """One shared connection to the physical board. MI and EMG sources both
    pull from this instead of each opening their own connection."""

    def __init__(self):
        self.board = None
        self.is_connected = False
        self.last_error = None
        self.sampling_rate = None
        self._connect()

    def _connect(self):
        if not HAS_BRAINFLOW:
            self.last_error = "brainflow not installed — run: pip install brainflow numpy"
            return
        try:
            params = BrainFlowInputParams()
            self.board = BoardShim(GANGLION_BOARD_ID, params)
            self.board.prepare_session()
            self.board.start_stream()
            self.sampling_rate = BoardShim.get_sampling_rate(GANGLION_BOARD_ID)
            self.is_connected = True
            print("🧠 [GANGLION]: Connected and streaming.")
        except Exception as e:
            self.last_error = f"Ganglion board not found or failed to start: {e}"

    def reconnect(self):
        if self.is_connected:
            return
        self._connect()

    def _latest_channel_power(self, channel_index, window_sec=0.5):
        """Variance (power) of the most recent short window on one channel —
        same measure the earlier eeg_pipeline.py design used."""
        window_size = max(2, int(self.sampling_rate * window_sec))
        data = self.board.get_current_board_data(window_size)
        if data.shape[1] < window_size:
            return 0.0
        signal = data[channel_index]
        DataFilter.perform_bandpass(signal, self.sampling_rate, 19.0, 11.0, 4,
                                     FilterTypes.BUTTERWORTH.value, 0.0)
        return float(np.var(signal))

    def get_mi_sample(self):
        """Returns (c3_power, c4_power, None) — matches SyntheticEEGSource's
        3-value shape, with None where the synthetic version had ground truth."""
        if not self.is_connected:
            return 0.0, 0.0, None
        eeg_channels = BoardShim.get_eeg_channels(GANGLION_BOARD_ID)
        c3 = self._latest_channel_power(eeg_channels[0])
        c4 = self._latest_channel_power(eeg_channels[1]) if len(eeg_channels) > 1 else c3
        return c3, c4, None

    def get_emg_sample(self):
        """Returns (raw_emg_microvolts, None) — channel 3, bipolar muscle signal."""
        if not self.is_connected:
            return 0.0, None
        eeg_channels = BoardShim.get_eeg_channels(GANGLION_BOARD_ID)
        if len(eeg_channels) < 3:
            return 0.0, None
        data = self.board.get_current_board_data(1)
        if data.shape[1] < 1:
            return 0.0, None
        return float(data[eeg_channels[2]][-1]), None

    def shutdown(self):
        if self.board and self.is_connected:
            try:
                self.board.stop_stream()
                self.board.release_session()
            except Exception:
                pass


_shared_board = None


def get_shared_board():
    """Both RealEEGSource and RealEMGSource call this — guarantees they share
    the same physical connection instead of each opening their own."""
    global _shared_board
    if _shared_board is None:
        _shared_board = GanglionBoard()
    return _shared_board


class RealEEGSource:
    """Drop-in replacement for SyntheticEEGSource — same next_sample() shape,
    same is_connected/last_error/reconnect() interface as ps_detector.py."""

    def __init__(self):
        self.board = get_shared_board()

    @property
    def is_connected(self):
        return self.board.is_connected

    @property
    def last_error(self):
        return self.board.last_error

    def reconnect(self):
        self.board.reconnect()

    def next_sample(self):
        return self.board.get_mi_sample()


class RealEMGSource:
    """Drop-in replacement for SyntheticEMGSource — same interface as above."""

    def __init__(self):
        self.board = get_shared_board()

    @property
    def is_connected(self):
        return self.board.is_connected

    @property
    def last_error(self):
        return self.board.last_error

    def reconnect(self):
        self.board.reconnect()

    def next_sample(self):
        return self.board.get_emg_sample()


# --- What the swap-in looks like, once the headband is confirmed working ---
# In aispe.py, change:
#     from mi_detector import SyntheticEEGSource, MIDetector
#     from emg_detector import SyntheticEMGSource, EMGDetector
# to:
#     from mi_detector import MIDetector
#     from emg_detector import EMGDetector
#     from real_hardware_source import RealEEGSource, RealEMGSource
# then replace SyntheticEEGSource(...) with RealEEGSource() and
# SyntheticEMGSource(...) with RealEMGSource(). MIDetector/EMGDetector and
# everything downstream needs no changes at all.
