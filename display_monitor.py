import sys
import threading
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from config import (
    COLOR_BACKGROUND, COLOR_TEXT_STANDARD, COLOR_TEXT_ACTIVE,
    COLOR_FLASH_RECEIVED, COLOR_SLEEP_TEXT, COLOR_SLEEP_STANDBY,
)

class DisplayMonitor(QMainWindow):
    signal_flash_trigger = pyqtSignal()
    signal_update_text = pyqtSignal(str)
    signal_update_focus = pyqtSignal(str, str)
    signal_toggle_sleep = pyqtSignal(bool)
    signal_hardware_disconnected = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.init_ui_canvas()
        self.running = True

    def init_ui_canvas(self):
        self.setWindowTitle("Auditory BMI Display Monitor")
        self.setGeometry(100, 100, 1024, 768)
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        top_layout = QHBoxLayout()
        self.lbl_mode = QLabel("LIVE MODE: PHYSICAL SWITCH (PS)")
        self.lbl_mode.setFont(QFont("MS Gothic", 20, QFont.Weight.Bold))
        self.lbl_mode.setStyleSheet(f"color: {COLOR_TEXT_STANDARD};")

        self.lbl_pulse_box = QLabel("[ WAITING ]")
        self.lbl_pulse_box.setFont(QFont("MS Gothic", 20, QFont.Weight.Bold))
        self.lbl_pulse_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pulse_box.setFixedSize(220, 50)
        self.lbl_pulse_box.setStyleSheet("color: #7A7A7A; border: 3px solid #7A7A7A; border-radius: 5px;")

        top_layout.addWidget(self.lbl_mode)
        top_layout.addStretch()
        top_layout.addWidget(self.lbl_pulse_box)
        main_layout.addLayout(top_layout)

        self.middle_container = QWidget()
        self.middle_container.setStyleSheet("border: 2px dashed #2A2A2A; border-radius: 10px;")
        mid_layout = QVBoxLayout(self.middle_container)
        mid_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_focus_title = QLabel("CURRENT TARGET FOCUS:")
        lbl_focus_title.setFont(QFont("MS Gothic", 16, QFont.Weight.Bold))
        lbl_focus_title.setStyleSheet("color: #555555;")
        lbl_focus_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_active_target = QLabel(">>>>  あ行 (A-Row)  <<<<")
        self.lbl_active_target.setFont(QFont("MS Gothic", 64, QFont.Weight.Bold))
        self.lbl_active_target.setStyleSheet(f"color: {COLOR_TEXT_ACTIVE};")
        self.lbl_active_target.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_sub_options = QLabel("[あ]  [い]  [う]  [え]  [お]  [前]")
        self.lbl_sub_options.setFont(QFont("MS Gothic", 24))
        self.lbl_sub_options.setStyleSheet(f"color: {COLOR_TEXT_STANDARD};")
        self.lbl_sub_options.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mid_layout.addWidget(lbl_focus_title)
        mid_layout.addWidget(self.lbl_active_target)
        mid_layout.addWidget(self.lbl_sub_options)
        main_layout.addWidget(self.middle_container, stretch=2)

        bot_layout = QVBoxLayout()
        lbl_output_title = QLabel("COMPOSED TEXT OUTPUT:")
        lbl_output_title.setFont(QFont("MS Gothic", 16, QFont.Weight.Bold))
        lbl_output_title.setStyleSheet("color: #555555;")

        self.lbl_sentence_output = QLabel("")
        self.lbl_sentence_output.setFont(QFont("MS Gothic", 110, QFont.Weight.Bold))
        self.lbl_sentence_output.setStyleSheet(f"color: {COLOR_TEXT_STANDARD};")
        self.lbl_sentence_output.setWordWrap(True)

        bot_layout.addWidget(lbl_output_title)
        bot_layout.addWidget(self.lbl_sentence_output)
        main_layout.addLayout(bot_layout, stretch=3)

        self.signal_flash_trigger.connect(self.execute_visual_flash_slot)
        self.signal_update_text.connect(self.update_sentence_slot)
        self.signal_update_focus.connect(self.update_matrix_focus_slot)
        self.signal_toggle_sleep.connect(self.toggle_sleep_profile_slot)
        self.signal_hardware_disconnected.connect(self.set_hardware_disconnected_slot)

        self._hardware_disconnected = False

    @pyqtSlot()
    def execute_visual_flash_slot(self):
        if self._hardware_disconnected:
            return  # Don't let a stray flash mask the disconnect warning
        self.lbl_pulse_box.setText("[ RECEIVED ]")
        self.lbl_pulse_box.setStyleSheet(f"color: {COLOR_FLASH_RECEIVED}; background-color: #330000; border: 3px solid {COLOR_FLASH_RECEIVED}; border-radius: 5px;")
        QTimer.singleShot(400, self.reset_pulse_box)

    def reset_pulse_box(self):
        if "[ STANDBY ]" in self.lbl_pulse_box.text():
            return
        if self._hardware_disconnected:
            return
        self.lbl_pulse_box.setText("[ WAITING ]")
        self.lbl_pulse_box.setStyleSheet("color: #7A7A7A; border: 3px solid #7A7A7A; border-radius: 5px;")

    @pyqtSlot(str)
    def update_sentence_slot(self, text_string):
        # Longer sentences shrink to fit and wrap onto more lines, instead of
        # running off the bottom of the screen at a fixed huge size.
        length = len(text_string)
        if length <= 8:
            size = 110
        elif length <= 16:
            size = 80
        elif length <= 28:
            size = 60
        else:
            size = 44
        self.lbl_sentence_output.setFont(QFont("MS Gothic", size, QFont.Weight.Bold))
        self.lbl_sentence_output.setText(text_string)

    @pyqtSlot(str, str)
    def update_matrix_focus_slot(self, primary_heading, sub_options_string):
        self.lbl_active_target.setText(primary_heading)
        self.lbl_sub_options.setText(sub_options_string)

    @pyqtSlot(bool)
    def toggle_sleep_profile_slot(self, enable_sleep):
        if enable_sleep:
            self.lbl_mode.setText("SYSTEM STATUS: SLEEP MODE ACTIVE")
            self.lbl_mode.setStyleSheet(f"color: {COLOR_SLEEP_TEXT};")
            self.lbl_pulse_box.setText("[ STANDBY ]")
            self.lbl_pulse_box.setStyleSheet(f"color: {COLOR_SLEEP_STANDBY}; border: 3px solid {COLOR_SLEEP_STANDBY}; border-radius: 5px;")
            self.lbl_active_target.setText("[ AUDITORY LOOP PAUSED ]")
            self.lbl_active_target.setStyleSheet(f"color: {COLOR_SLEEP_TEXT};")
            self.lbl_sub_options.setText("Single Pulse Input Required to Reactivate")
            self.lbl_sub_options.setStyleSheet(f"color: {COLOR_SLEEP_TEXT};")
            self.lbl_sentence_output.setStyleSheet(f"color: {COLOR_SLEEP_TEXT};")
        else:
            self.lbl_mode.setText("LIVE MODE: PHYSICAL SWITCH (PS)")
            self.lbl_mode.setStyleSheet(f"color: {COLOR_TEXT_STANDARD};")
            self.reset_pulse_box()
            self.lbl_active_target.setStyleSheet(f"color: {COLOR_TEXT_ACTIVE};")
            self.lbl_sub_options.setStyleSheet(f"color: {COLOR_TEXT_STANDARD};")
            self.lbl_sentence_output.setStyleSheet(f"color: {COLOR_TEXT_STANDARD};")

    @pyqtSlot(bool)
    def set_hardware_disconnected_slot(self, is_disconnected):
        """Explicit, unmissable state for when the input hardware stops responding."""
        self._hardware_disconnected = is_disconnected
        if is_disconnected:
            self.lbl_pulse_box.setText("[ DISCONNECTED ]")
            self.lbl_pulse_box.setStyleSheet(f"color: {COLOR_FLASH_RECEIVED}; background-color: #330000; border: 4px solid {COLOR_FLASH_RECEIVED}; border-radius: 5px;")
            self.lbl_mode.setText("⚠ HARDWARE INPUT LOST — CHECK CONNECTION ⚠")
            self.lbl_mode.setStyleSheet(f"color: {COLOR_FLASH_RECEIVED};")
        else:
            self.lbl_mode.setText("LIVE MODE: PHYSICAL SWITCH (PS)")
            self.lbl_mode.setStyleSheet(f"color: {COLOR_TEXT_STANDARD};")
            self.reset_pulse_box()

    def simulate_hardware_background_thread(self):
        import keyboard
        while self.running:
            if keyboard.is_pressed('space'):
                self.signal_flash_trigger.emit()
                time.sleep(0.4)
            time.sleep(0.01)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.running = False
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DisplayMonitor()
    window.showFullScreen()
    test_thread = threading.Thread(target=window.simulate_hardware_background_thread, daemon=True)
    test_thread.start()
    sys.exit(app.exec())
