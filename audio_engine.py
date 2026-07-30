import time
import sys
import threading
import pyttsx3
import winsound
from config import SCAN_WINDOW_TIMEOUT, POST_SELECTION_RESET, TTS_VOICE_RATE, HARDWARE_DEBOUNCE

# --- INTERFACE GRID SPECS (CSGF) ---
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
    "メニュー行": ["スペース", "読み上げ", "一文字消去", "全消去", "休止モード", "前"]
}

class WindowsAudioEngine:
    def __init__(self):
        self.running = True
        self.input_triggered = threading.Event()
        self.composed_sentence = []
        self.on_sentence_change = None   # optional callable(full_text: str)
        self.on_focus_update = None      # optional callable(row_name: str, current_option: str)
        self.sleep_mode = False

        self._voice_id = None    # resolved once at startup, reused for every phrase
        self._voice_name = None

        self.row_keys = list(HIRAGANA_MATRIX.keys())

        self._build_sounds()

    def _play_chime(self, freq_sequence, duration_each_ms=90):
        """Plays a short beep or sequence of beeps using Windows' built-in sound module.
        No installed library needed — winsound ships with every Windows Python install."""
        for freq in freq_sequence:
            winsound.Beep(int(freq), int(duration_each_ms))

    def _build_sounds(self):
        """Defines every non-verbal confirmation cue used across the auditory loop, as
        (frequencies, duration_ms) pairs — played on demand via _play_chime."""
        self.snd_confirm = ([880], 100)          # sharp selection lock chime
        self.snd_back = ([600, 400], 90)         # distinct 前 reverse-nav chime
        self.snd_bell = ([1046, 1318], 220)      # boxing-bell "TING!"
        self.snd_sleep = ([700, 500, 300], 150)  # fading chime into sleep mode
        self.snd_wake = ([500, 900], 120)        # wake-up chime

    def setup_masculine_voice(self):
        """Resolves which Japanese voice to use, once, and caches its id. No longer requires
        Ichiro specifically — any installed Japanese voice (e.g. Haruka) works fine."""
        probe_engine = pyttsx3.init('sapi5')
        voices = probe_engine.getProperty('voices')
        for v in voices:
            if "japanese" in v.name.lower() or "ja-jp" in str(getattr(v, "id", "")).lower():
                self._voice_id = v.id
                self._voice_name = v.name
                break
        probe_engine.stop()
        del probe_engine

        if self._voice_id:
            print(f"🔊 [VOICE]: Using '{self._voice_name}' for Japanese speech output.")
        else:
            print("⚠️ [VOICE]: No Japanese voice found — falling back to the system default. "
                  "Add a Japanese voice via Settings > Time & Language > Speech if output sounds wrong.")

    def _speak(self, text):
        """Speaks one phrase using a brand-new engine each time. SAPI5 via pyttsx3 is known to
        speak once and then silently hang on later calls if the same engine object is reused —
        creating a fresh one per phrase avoids that entirely."""
        engine = pyttsx3.init('sapi5')
        if self._voice_id:
            engine.setProperty('voice', self._voice_id)
        engine.setProperty('rate', TTS_VOICE_RATE)
        engine.say(text)
        engine.runAndWait()
        try:
            engine.stop()
        except Exception:
            pass
        del engine

    def listen_for_keyboard_simulation(self):
        print("\n[AUDIO ENGINE SIMULATION INTERFACE ACTIVE]")
        import keyboard
        while self.running:
            if keyboard.is_pressed('space'):
                if not self.input_triggered.is_set():
                    self.input_triggered.set()
                time.sleep(HARDWARE_DEBOUNCE)
            elif keyboard.is_pressed('esc'):
                self.running = False
                self.input_triggered.set()
            time.sleep(0.01)

    def speak_interruptible(self, text, is_bell=False, spoken_text=None):
        self.input_triggered.clear()
        if is_bell:
            self._play_chime(*self.snd_bell)  # Menu row: silent "TING!" bell only, per spec — no spoken word
        else:
            self._speak(spoken_text if spoken_text is not None else text)

        start_time = time.time()
        while time.time() - start_time < SCAN_WINDOW_TIMEOUT:
            if self.input_triggered.is_set():
                # Instant non-verbal lock confirmation, before any spoken feedback
                if text == "前":
                    self._play_chime(*self.snd_back)
                else:
                    self._play_chime(*self.snd_confirm)
                return True
            time.sleep(0.02)
        return False

    def process_selection(self, choice, current_row_idx):
        if not self.running:
            return current_row_idx

        if choice == "前":
            self._speak("前")
            new_idx = (current_row_idx - 1) % len(self.row_keys)
            return new_idx

        self._speak(choice)

        if choice == "スペース":
            self.composed_sentence.append(" ")
        elif choice == "読み上げ":
            full_text = "".join(self.composed_sentence)
            self._speak(full_text if full_text else "空欄")
        elif choice == "一文字消去":
            if self.composed_sentence:
                self.composed_sentence.pop()
        elif choice == "全消去":
            self.composed_sentence.clear()
        elif choice == "休止モード":
            self.execute_sleep_sequence()
        else:
            self.composed_sentence.append(choice)

        if self.on_sentence_change:
            self.on_sentence_change("".join(self.composed_sentence))

        time.sleep(POST_SELECTION_RESET)
        return 0

    def execute_sleep_sequence(self):
        self.sleep_mode = True
        self.input_triggered.clear()
        self._play_chime(*self.snd_sleep)
        while self.sleep_mode and self.running:
            if self.input_triggered.is_set():
                self._play_chime(*self.snd_wake)
                self._speak("再開します")
                self.sleep_mode = False
                self.input_triggered.clear()
            time.sleep(0.05)

    def _row_reading(self, row_name):
        """The kanji 行 has several valid readings (ぎょう/こう/etc.) and the TTS engine
        guesses inconsistently. Spell out the intended one explicitly for speech only —
        the on-screen text keeps showing '行' as written."""
        if row_name.endswith("行"):
            return row_name[:-1] + "ぎょう"
        return row_name

    def start_engine(self):
        # Resolve which voice to use once, on the thread that will actually speak
        # (every phrase gets its own fresh engine — see _speak()).
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass  # pythoncom isn't always needed depending on the pyttsx3 driver in use
        self.setup_masculine_voice()

        row_idx = 0
        while self.running:
            current_row_name = self.row_keys[row_idx]
            is_menu_bell = (current_row_name == "メニュー行")
            if self.on_focus_update:
                self.on_focus_update(current_row_name, "")
            hit = self.speak_interruptible(current_row_name, is_bell=is_menu_bell,
                                            spoken_text=self._row_reading(current_row_name))
            if not self.running:
                break
            if hit:
                tier_selection = None
                while tier_selection is None and self.running:
                    for char_opt in HIRAGANA_MATRIX[current_row_name]:
                        if self.on_focus_update:
                            self.on_focus_update(current_row_name, char_opt)
                        char_hit = self.speak_interruptible(char_opt)
                        if not self.running:
                            break
                        if char_hit:
                            tier_selection = char_opt
                            row_idx = self.process_selection(tier_selection, row_idx)
                            break
            else:
                row_idx = (row_idx + 1) % len(self.row_keys)

if __name__ == "__main__":
    engine = WindowsAudioEngine()
    sim_thread = threading.Thread(target=engine.listen_for_keyboard_simulation, daemon=True)
    sim_thread.start()
    try:
        engine.start_engine()
    except KeyboardInterrupt:
        pass
