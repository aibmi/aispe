import sys
import threading
import time
from PyQt6.QtWidgets import QApplication

from display_monitor import DisplayMonitor
from audio_engine import WindowsAudioEngine
from input_driver import PacificSupplyDriver
from eeg_pipeline import BrainFlowEEGPipeline

# Set this to "PS", "MI", or "TEST" depending on what's available right now.
# "TEST" needs no hardware at all — press Enter to simulate a selection.
INPUT_MODE = "TEST"


class IntegratedBMISystem:
    def __init__(self, input_mode=INPUT_MODE):
        self.input_mode = input_mode
        self.app = QApplication(sys.argv)

        self.monitor = DisplayMonitor()
        self.monitor.showFullScreen()

        self.audio_engine = WindowsAudioEngine()

        # Only build the driver for the mode actually in use.
        # This is what keeps a disconnected PS switch from raising a false
        # alarm while running in MI mode, and vice versa.
        self.ps_driver = None
        self.mi_driver = None

        if self.input_mode == "PS":
            self.ps_driver = PacificSupplyDriver(key_bind="space")
            self.ps_driver.on_disconnect = self._handle_active_driver_disconnect
        elif self.input_mode == "MI":
            self.mi_driver = BrainFlowEEGPipeline(use_synthetic=True)
            self.mi_driver.on_disconnect = self._handle_active_driver_disconnect
        elif self.input_mode == "TEST":
            # No real switch present, so no real disconnect is possible —
            # on_disconnect is deliberately left unset here.
            self.ps_driver = PacificSupplyDriver(key_bind="space")
        else:
            raise ValueError(f"Unknown INPUT_MODE: {self.input_mode!r} (expected 'PS', 'MI', or 'TEST')")

    def _handle_active_driver_disconnect(self, reason):
        """Only ever called by whichever driver is actually in use — see __init__."""
        print(f"[WARNING] Active input hardware disconnected: {reason}")
        self.monitor.signal_hardware_disconnected.emit(True)

    def _bridge_active_driver_to_engine(self):
        """Watches the one active input channel and forwards pulses to the audio engine + screen flash."""
        def watch_ps():
            while self.audio_engine.running:
                if self.ps_driver.catch_trigger_pulse(timeout_window=0.05):
                    self.monitor.signal_flash_trigger.emit()
                    self.audio_engine.input_triggered.set()
                time.sleep(0.01)

        def watch_mi():
            while self.audio_engine.running:
                if self.mi_driver.wait_for_eeg_action(scan_window_timeout=0.05):
                    self.monitor.signal_flash_trigger.emit()
                    self.audio_engine.input_triggered.set()
                time.sleep(0.01)

        target = watch_ps if self.input_mode in ("PS", "TEST") else watch_mi
        threading.Thread(target=target, daemon=True).start()

    def execute_system(self):
        if self.input_mode == "PS":
            self.monitor.lbl_mode.setText("LIVE MODE: PHYSICAL SWITCH (PS)")
            self.ps_driver.start_driver()
        elif self.input_mode == "MI":
            self.monitor.lbl_mode.setText("LIVE MODE: MOTOR IMAGERY (MI)")
            self.mi_driver.start_pipeline()
        else:  # TEST
            self.monitor.lbl_mode.setText("TEST MODE — PRESS SPACE (NO HARDWARE ATTACHED)")
            self.ps_driver.start_driver()

        self._bridge_active_driver_to_engine()

        audio_loop_thread = threading.Thread(target=self.audio_engine.start_engine, daemon=True)
        audio_loop_thread.start()

        sys.exit(self.app.exec())


if __name__ == "__main__":
    system = IntegratedBMISystem()
    system.execute_system()
