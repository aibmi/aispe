"""
aispe2 — parallel prototype build, for comparison against master_assembly.py

What's different here, on purpose:
  1. Speech goes through Qt's own QTextToSpeech instead of a raw SAPI5 COM
     connection. Qt's speech module is built to run safely on the same
     thread as the rest of the app, using signals instead of blocking calls.
  2. Enter-key input is read directly from Qt's own keyPressEvent, instead
     of a separate background thread polling the keyboard many times a
     second. One thread, one event loop, nothing running in parallel with
     the speech engine.
  3. The scanning logic (which row/character, timing, menu handling) and
     the actual speaking/display are still fairly interleaved here for the
     sake of a compact single-file prototype — a fuller rewrite would
     separate those further, as discussed.

This is a TEST-mode-only prototype (Enter key, no PS/MI hardware) meant to
answer one question: does moving off raw SAPI fix the crackle? It is not
yet a feature-complete replacement for master_assembly.py.

Install: pip install PyQt6
(If QTextToSpeech fails to import, it may need a separate wheel on some
setups: pip install PyQt6-QtTextToSpeech)
"""

import sys
import winsound
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer, QLocale
from PyQt6.QtGui import QFont
from PyQt6.QtTextToSpeech import QTextToSpeech
from mi_detector import SyntheticEEGSource, MIDetector
from emg_detector import SyntheticEMGSource, EMGDetector

# Which input mode starts active. Switch anytime while running — no code
# edits needed — with these keys:
#   M = Motor Imagery (brain)      E = EMG (muscle)
#   P = Physical Switch            S = Space test mode
# Only one mode drives selections at a time; the others keep listening in
# the background so switching is instant, but only the active one can
# actually trigger a selection.
DEFAULT_MODE = "S"

MODE_LABELS = {
    "M": "Motor Imagery (brain)",
    "E": "EMG (muscle)",
    "P": "Physical Switch",
    "S": "Space test mode",
}

SCAN_WINDOW_TIMEOUT_MS = 3000
POST_SELECTION_RESET_MS = 1000

HIRAGANA_MATRIX = {
    "あ行": ["あ", "い", "う", "え", "お", "前"],
    "か行": ["か", "き", "く", "け", "こ", "が", "ぎ", "ぐ", "げ", "ご", "前"],
    "さ行": ["さ", "し", "す", "せ", "そ", "ざ", "じ", "ず", "ぜ", "ぞ", "前"],
    "た行": ["た", "ち", "つ", "て", "と", "だ", "ぢ", "づ", "で", "ど", "前"],
    "な行": ["な", "に", "ぬ", "ね", "の", "前"],
    "は行": ["は", "ひ", "ふ", "へ", "ほ", "ば", "び", "ぶ", "べ", "ぼ", "ぱ", "ぴ", "ぷ", "ぺ", "ぽ", "前"],
    "ま行": ["ま", "み", "む", "め", "も", "前"],
    "や行": ["や", "ゆ", "よ", "前"],
    "ら行": ["ら", "り", "る", "れ", "ろ", "前"],
    "わ行": ["わ", "を", "ん", "ゃ", "ゅ", "ょ", "っ", "前"],
    "メニュー行": ["スペース", "読み上げ", "一文字消去", "全消去", "休止モード", "前"],
}


# --- Visual style ---
# A modern Japanese-compatible UI font instead of the old bitmap-style MS Gothic.
# Qt falls back automatically if a name isn't installed, so this is safe everywhere.
UI_FONT = "Yu Gothic UI"

COLOR_BG = "#14161B"          # dark charcoal-navy instead of pure black
COLOR_CARD_BG = "#1E212B"     # slightly lighter panel background, for visual separation
COLOR_CARD_BORDER = "#2E323F"
COLOR_MODE = "#7B8794"        # muted slate gray — status info, deprioritized on purpose
COLOR_FOCUS = "#60A5FA"       # clear blue — currently-scanned item, nowhere near red
COLOR_OUTPUT = "#EAB308"      # strong gold — the important, serious text, but not red
COLOR_HINT = "#5C6370"        # muted gray, unobtrusive but readable
COLOR_SLEEP = "#4B4F58"


class AispeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("aispe — auditory BMI communication system")
        self.setStyleSheet(f"background-color: {COLOR_BG};")
        self.resize(1024, 768)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        self._card_style = (
            f"background-color: {COLOR_CARD_BG}; "
            f"border: 1px solid {COLOR_CARD_BORDER}; "
            "border-radius: 14px; padding: 16px;"
        )
        card_style = self._card_style

        self.lbl_mode = QLabel("")
        self.lbl_mode.setFont(QFont(UI_FONT, 20, QFont.Weight.Bold))
        self.lbl_mode.setStyleSheet(f"color: {COLOR_MODE}; {card_style}")

        self.lbl_focus = QLabel(">>>> あ行 <<<<")
        self.lbl_focus.setFont(QFont(UI_FONT, 64, QFont.Weight.Bold))
        self.lbl_focus.setStyleSheet(f"color: {COLOR_FOCUS}; {card_style}")
        self.lbl_focus.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_output = QLabel("")
        self.lbl_output.setFont(QFont(UI_FONT, 110, QFont.Weight.Bold))
        self.lbl_output.setStyleSheet(f"color: {COLOR_OUTPUT}; {card_style}")
        self.lbl_output.setWordWrap(True)

        self.lbl_controls = QLabel(
            "type M for Motor Imagery - brain mode , E for EMG - muscle mode, "
            "P for Physical Switch mode, S for Space test mode, ESC to Exit"
        )
        self.lbl_controls.setFont(QFont(UI_FONT, 13))
        self.lbl_controls.setStyleSheet(f"color: {COLOR_HINT}; padding: 4px 4px;")

        layout.addWidget(self.lbl_mode)
        layout.addWidget(self.lbl_focus, stretch=2)
        layout.addWidget(self.lbl_output, stretch=3)
        layout.addWidget(self.lbl_controls)

        # --- Speech: Qt's own tool, same thread as everything else ---
        self.tts = QTextToSpeech()
        self.tts.stateChanged.connect(self.on_tts_state_changed)
        self._pick_japanese_voice()

        # --- Scan state ---
        self.row_keys = list(HIRAGANA_MATRIX.keys())
        self.row_idx = 0
        self.tier = 1          # 1 = scanning rows, 2 = scanning characters within a row
        self.char_idx = 0
        self.composed_sentence = []
        self.sleep_mode = False
        self.waiting_for_input = False

        self.response_timer = QTimer(self)
        self.response_timer.setSingleShot(True)
        self.response_timer.timeout.connect(self.on_response_timeout)

        self.reset_timer = QTimer(self)
        self.reset_timer.setSingleShot(True)
        self.reset_timer.timeout.connect(self.return_to_row_scan_start)

        # Speech sequencing: Qt's speech tool interrupts itself if you call say() again
        # before the previous phrase finishes. This queues phrases so multi-step speech
        # (e.g. chime -> character name -> read-back) always completes in order.
        self._pending_speech = []
        self._speech_on_done = None

        # --- All input sources run continuously in the background — this is what
        # makes switching modes with a keypress instant, with no re-initialization.
        # Only the ACTIVE mode is allowed to actually trigger a selection. ---
        self.active_mode = DEFAULT_MODE

        # MI (brain) — synthetic until real EEG hardware is connected
        self.mi_source = SyntheticEEGSource(event_probability=0.003)
        self.mi_detector = MIDetector()
        self.mi_timer = QTimer(self)
        self.mi_timer.timeout.connect(self._poll_mi_input)
        self.mi_timer.start(50)  # ~20 samples/sec, matching the test harness's pacing

        # EMG (muscle) — synthetic until real hardware is connected
        self.emg_source = SyntheticEMGSource(event_probability=0.003)
        self.emg_detector = EMGDetector()
        self.emg_timer = QTimer(self)
        self.emg_timer.timeout.connect(self._poll_emg_input)
        self.emg_timer.start(50)

        # P (Physical Switch) — placeholder: bound to Enter for now, since no real
        # switch driver is wired into aispe yet. Swap this for a real serial-port
        # driver once the PS switch hardware is actually connected.

        self.lbl_mode.setText(self._mode_label())

        self.begin_row_scan()

    def set_active_mode(self, mode_key):
        """Switches which input source can trigger a selection. All sources keep
        running in the background regardless — this just changes which one is
        allowed through to handle_pulse()."""
        if mode_key not in MODE_LABELS:
            return
        self.active_mode = mode_key
        if self.sleep_mode:
            return  # sleep-mode label stays showing the wake hint until woken
        self.lbl_mode.setText(self._mode_label())

    def _mode_label(self):
        return f"ACTIVE MODE: {MODE_LABELS[self.active_mode]}"

    def _poll_mi_input(self):
        """Pulls one synthetic C3/C4 sample and feeds it to the detector. Runs
        regardless of the active mode, so switching to M is instant — but only
        forwards to handle_pulse() when MI is actually the active mode."""
        c3, c4, _ = self.mi_source.next_sample()
        triggered = self.mi_detector.update(c3, c4)
        if triggered and self.active_mode == "M":
            self.handle_pulse()

    def _poll_emg_input(self):
        """Same idea as _poll_mi_input, for the EMG channel."""
        raw, _ = self.emg_source.next_sample()
        triggered = self.emg_detector.update(raw)
        if triggered and self.active_mode == "E":
            self.handle_pulse()

    # --- Voice setup ---

    def _pick_japanese_voice(self):
        voices = self.tts.availableVoices()
        jp_voices = [v for v in voices if v.locale().language() == QLocale.Language.Japanese]

        print(f"🔊 [aispe2 VOICE]: Found {len(jp_voices)} Japanese voice(s):")
        for v in jp_voices:
            print(f"    - {v.name()}")

        modern = [v for v in jp_voices if "desktop" not in v.name().lower()]
        pick_from = modern if modern else jp_voices

        # Quick manual override for trying different voices — set to a name substring
        # (case-insensitive), or None to use the automatic preference below.
        FORCE_VOICE = "haruka"

        if FORCE_VOICE:
            forced = [v for v in jp_voices if FORCE_VOICE.lower() in v.name().lower()]
            forced_modern = [v for v in forced if "desktop" not in v.name().lower()]
            if forced_modern:
                pick_from = forced_modern
            elif forced:
                pick_from = forced

        ichiro = [v for v in pick_from if "ichiro" in v.name().lower()]
        chosen = ichiro[0] if ichiro else (pick_from[0] if pick_from else None)

        if chosen:
            self.tts.setVoice(chosen)
            print(f"🔊 [aispe2 VOICE]: Using '{chosen.name()}'")
        else:
            print("⚠️ [aispe2 VOICE]: No Japanese voice found — using whatever default is set.")

    # --- Row/character reading helpers ---

    def _row_reading(self, row_name):
        if row_name.endswith("行"):
            return row_name[:-1] + "ぎょう"
        return row_name

    # --- Scanning flow ---

    def begin_row_scan(self):
        self.tier = 1
        self.char_idx = 0
        current_row = self.row_keys[self.row_idx]
        self.lbl_focus.setText(f">>>> {current_row} <<<<")

        if current_row == "メニュー行":
            winsound.Beep(1046, 220)
            winsound.Beep(1318, 220)
            self.start_response_window()
        else:
            self.waiting_for_input = True  # accept a press from the moment speech starts
            self._speak_sequence([self._row_reading(current_row)])
            # response TIMER starts once speech finishes — see on_tts_state_changed

    def speak_current_char(self):
        current_row = self.row_keys[self.row_idx]
        options = HIRAGANA_MATRIX[current_row]
        char_opt = options[self.char_idx]
        self.lbl_focus.setText(f">>>> {current_row}: {char_opt} <<<<")
        self.waiting_for_input = True  # accept a press from the moment speech starts
        self._speak_sequence([char_opt])

    def _speak_sequence(self, texts, on_done=None):
        """Speaks a list of phrases one after another, waiting for each to finish before
        starting the next, then calls on_done() once all of them are spoken."""
        self._pending_speech = list(texts)
        self._speech_on_done = on_done
        self._advance_speech_sequence()

    def _advance_speech_sequence(self):
        if self._pending_speech:
            text = self._pending_speech.pop(0)
            self.tts.say(text)
        elif self._speech_on_done:
            callback = self._speech_on_done
            self._speech_on_done = None
            callback()

    def on_tts_state_changed(self, state):
        if state != QTextToSpeech.State.Ready:
            return
        if self._pending_speech:
            self._advance_speech_sequence()
            return
        if self._speech_on_done:
            callback = self._speech_on_done
            self._speech_on_done = None
            callback()
            return
        if not self.sleep_mode:
            self.start_response_window()

    def start_response_window(self):
        self.waiting_for_input = True
        self.response_timer.start(SCAN_WINDOW_TIMEOUT_MS)

    def on_response_timeout(self):
        self.waiting_for_input = False
        if self.tier == 1:
            self.row_idx = (self.row_idx + 1) % len(self.row_keys)
            self.begin_row_scan()
        else:
            current_row = self.row_keys[self.row_idx]
            options = HIRAGANA_MATRIX[current_row]
            self.char_idx = (self.char_idx + 1) % len(options)
            self.speak_current_char()

    def return_to_row_scan_start(self):
        self.row_idx = 0
        self.begin_row_scan()

    # --- Input handling (Qt's own key events — no separate polling thread) ---

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return  # a held-down key shouldn't count as repeated presses

        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.close()
            return

        if key == Qt.Key.Key_M:
            self.set_active_mode("M")
            return
        if key == Qt.Key.Key_E:
            self.set_active_mode("E")
            return
        if key == Qt.Key.Key_P:
            self.set_active_mode("P")
            return
        if key == Qt.Key.Key_S:
            self.set_active_mode("S")
            return

        # S = Space test mode: only Space triggers, and only while S is active
        if key == Qt.Key.Key_Space and self.active_mode == "S":
            self.handle_pulse()
            return

        # P = Physical Switch: placeholder bound to Enter until real switch
        # hardware is wired in — only fires while P is active
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.active_mode == "P":
            self.handle_pulse()
            return

        super().keyPressEvent(event)

    def handle_pulse(self):
        if self.sleep_mode:
            self.wake_up()
            return
        if not self.waiting_for_input:
            return
        self.response_timer.stop()
        self.waiting_for_input = False
        if self.tier == 1:
            winsound.Beep(880, 100)  # confirm chime
            self.tier = 2
            self.char_idx = 0
            self.speak_current_char()
        else:
            self.select_character()

    # --- Selection handling ---

    def select_character(self):
        current_row = self.row_keys[self.row_idx]
        options = HIRAGANA_MATRIX[current_row]
        choice = options[self.char_idx]

        if choice == "前":
            winsound.Beep(600, 90)
            winsound.Beep(400, 90)
            self.row_idx = (self.row_idx - 1) % len(self.row_keys)
            self._speak_sequence(["前"], on_done=self.begin_row_scan)
            return

        winsound.Beep(880, 100)

        if choice == "スペース":
            self.composed_sentence.append(" ")
        elif choice == "一文字消去":
            if self.composed_sentence:
                self.composed_sentence.pop()
        elif choice == "全消去":
            self.composed_sentence.clear()
        elif choice == "読み上げ":
            pass  # nothing to add to the sentence — see the speech block below
        elif choice == "休止モード":
            self._speak_sequence([choice], on_done=self.enter_sleep_mode)
            return
        else:
            self.composed_sentence.append(choice)

        self.update_output_display()

        if choice == "読み上げ":
            full_text = "".join(self.composed_sentence)
            speech = [choice, full_text if full_text else "空欄"]
        else:
            speech = [choice]

        self._speak_sequence(speech, on_done=lambda: self.reset_timer.start(POST_SELECTION_RESET_MS))

    def update_output_display(self):
        text = "".join(self.composed_sentence)
        length = len(text)
        size = 110 if length <= 8 else 80 if length <= 16 else 60 if length <= 28 else 44
        self.lbl_output.setFont(QFont(UI_FONT, size, QFont.Weight.Bold))
        self.lbl_output.setText(text)

    def enter_sleep_mode(self):
        self.sleep_mode = True
        winsound.Beep(700, 150)
        winsound.Beep(500, 150)
        winsound.Beep(300, 150)
        wake_hints = {"M": "imagine the trigger to wake", "E": "trigger the muscle to wake",
                      "P": "press the switch to wake", "S": "press Space to wake"}
        self.lbl_mode.setText(f"SLEEP MODE — {wake_hints[self.active_mode]}")
        self.lbl_focus.setText("[ AUDITORY LOOP PAUSED ]")

        # Dim everything to a muted gray — visibly paused, not just different text.
        # Output text stays frozen on screen (not cleared) but dimmed, same as the
        # original design intent: nothing is lost, it's just not the active state.
        self.lbl_mode.setStyleSheet(f"color: {COLOR_SLEEP}; {self._card_style}")
        self.lbl_focus.setStyleSheet(f"color: {COLOR_SLEEP}; {self._card_style}")
        self.lbl_output.setStyleSheet(f"color: {COLOR_SLEEP}; {self._card_style}")

    def wake_up(self):
        self.sleep_mode = False
        winsound.Beep(500, 120)
        winsound.Beep(900, 120)

        # Restore normal colors
        self.lbl_mode.setStyleSheet(f"color: {COLOR_MODE}; {self._card_style}")
        self.lbl_focus.setStyleSheet(f"color: {COLOR_FOCUS}; {self._card_style}")
        self.lbl_output.setStyleSheet(f"color: {COLOR_OUTPUT}; {self._card_style}")

        self.lbl_mode.setText(self._mode_label())
        self.row_idx = 0
        self._speak_sequence(["再開します"], on_done=self.begin_row_scan)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AispeWindow()
    window.showFullScreen()
    sys.exit(app.exec())
