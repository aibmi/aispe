import time
import sys
import threading
from config import HARDWARE_DEBOUNCE

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False


class PacificSupplyDriver:
    def __init__(self, key_bind="space", baud_rate=9600):
        self.running = True
        self.serial_conn = None
        self.baud_rate = baud_rate
        self.key_bind = key_bind
        self.hardware_pulse_event = threading.Event()
        self.connection_lost = threading.Event()
        self.on_disconnect = None  # optional callable(reason: str), set by whoever owns the caregiver display

    def auto_detect_usb_port(self):
        if not HAS_SERIAL:
            return None
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            if "serial" in p.description.lower() or "usb" in p.description.lower() or "ch340" in p.description.lower():
                return p.device
        if ports:
            return ports[0].device
        return None

    def initialize_switch_connection(self):
        target_port = self.auto_detect_usb_port()
        if target_port:
            try:
                self.serial_conn = serial.Serial(target_port, self.baud_rate, timeout=0.1)
                return True
            except Exception:
                pass
        return False

    def _serial_hardware_loop(self):
        if self.serial_conn:
            self.serial_conn.reset_input_buffer()
        while self.running and self.serial_conn:
            try:
                if self.serial_conn.in_waiting > 0:
                    raw_data = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    if raw_data in ["1", "SWITCH", "CLICK", "PUFF", "TRIGGER"]:
                        self.hardware_pulse_event.set()
            except Exception as e:
                self._report_disconnect(f"serial read failed: {e}")
                break
            time.sleep(0.005)

    def _report_disconnect(self, reason):
        """Marks the hardware as lost and notifies whoever is watching (e.g. the caregiver display)."""
        self.connection_lost.set()
        if self.on_disconnect:
            try:
                self.on_disconnect(reason)
            except Exception:
                pass  # A broken callback must never take down the input thread itself

    def is_hardware_connected(self):
        """True only while a live serial link is open and hasn't reported a failure."""
        return self.serial_conn is not None and not self.connection_lost.is_set()

    def _simulation_keyboard_loop(self):
        if not HAS_KEYBOARD:
            return
        while self.running and not self.serial_conn:
            if keyboard.is_pressed(self.key_bind):
                if not self.hardware_pulse_event.is_set():
                    self.hardware_pulse_event.set()
                time.sleep(HARDWARE_DEBOUNCE)
            time.sleep(0.01)

    def start_driver(self):
        has_hardware = self.initialize_switch_connection()
        if has_hardware:
            worker = threading.Thread(target=self._serial_hardware_loop, daemon=True)
        else:
            worker = threading.Thread(target=self._simulation_keyboard_loop, daemon=True)
        worker.start()

    def catch_trigger_pulse(self, timeout_window):
        self.hardware_pulse_event.clear()
        event_caught = self.hardware_pulse_event.wait(timeout=timeout_window)
        if event_caught:
            self.hardware_pulse_event.clear()
            return True
        return False

    def terminate_driver(self):
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
