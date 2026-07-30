import time
import sys
import threading
import pyttsx3
import pygame
import numpy as np
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
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
        self.running = True
        self.input_triggered = threading.Event()
        self.composed_sentence = []
        self.sleep_mode = False

        self.tts = pyttsx3.init('sapi5')
        self.setup_masculine_voice()

        self.row_keys = list(HIRAGANA_MATRIX.keys())

        self._build_sounds()

    def _make_tone(self, freq_sequence, duration_each=0.09, fade=True, volume=0.5):
        """Synthesizes a short tone (or sequence of tones) as a pygame Sound, no audio files needed."""
        sample_rate = 44100
        segments = []
        for freq in freq_sequence:
            n_samples = int(sample_rate * duration_each)
            t = np.linspace(0, duration_each, n_samples, False)
            wave = np.sin(freq * t * 2 * np.pi)
            if fade:
                fade_len = max(1, int(n_samples * 0.15))
                envelope = np.ones(n_samples)
                envelope[:fade_len] = np.linspace(0, 1, fade_len)
                envelope[-fade_len:] = np.linspace(1, 0, fade_len)
                wave *= envelope
            segments.append(wave)
        full_wave = np.concatenate(segments) * volume
        audio = np.int16(full_wave * 32767)
        stereo = np.column_stack([audio, audio])
        return pygame.sndarray.make_sound(np.ascontiguousarray(stereo))

    def _build_sounds(self):
        """Pre-builds every non-verbal confirmation cue used across the auditory loop."""
        self.snd_confirm = self._make_tone([880], duration_each=0.10)          # sharp selection lock chime
        self.snd_back = self._make_tone([600, 400], duration_each=0.09)        # distinct 前 reverse-nav chime
        self.snd_bell = self._make_tone([1046, 1318], duration_each=0.22, fade=True)  # boxing-bell "TING!"
        self.snd_sleep = self._make_tone([700, 500, 300], duration_each=0.15)  # fading chime into sleep mode
        self.snd_wake = self._make_tone([500, 900], duration_each=0.12)        # wake-up chime

    def setup_masculine_voice(self):
        """Picks the first available Japanese voice. No longer requires Ichiro specifically —
        any installed Japanese voice (e.g. Haruka) works fine for this system."""
        voices = self.tts.getProperty('voices')
        selected_voice = None
        selected_name = None
        for v in voices:
            if "japanese" in v.name.lower() or "ja-jp" in str(getattr(v, "id", "")).lower():
                selected_voice = v.id
                selected_name = v.name
                break
        if selected_voice:
            self.tts.setProperty('voice', selected_voice)
            print(f"🔊 [VOICE]: Using '{selected_name}' for Japanese speech output.")
        else:
            print("⚠️ [VOICE]: No Japanese voice found — falling back to the system default. "
                  "Add a Japanese voice via Settings > Time & Language > Speech if output sounds wrong.")
        self.tts.setProperty('rate', TTS_VOICE_RATE)

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

    def speak_interruptible(self, text, is_bell=False):
        self.input_triggered.clear()
        if is_bell:
            self.snd_bell.play()  # Menu row: silent "TING!" bell only, per spec — no spoken word
        else:
            self.tts.say(text)
            self.tts.runAndWait()

        start_time = time.time()
        while time.time() - start_time < SCAN_WINDOW_TIMEOUT:
            if self.input_triggered.is_set():
                # Instant non-verbal lock confirmation, before any spoken feedback
                if text == "前":
                    self.snd_back.play()
                else:
                    self.snd_confirm.play()
                return True
            time.sleep(0.02)
        return False

    def process_selection(self, choice, current_row_idx):
        if not self.running:
            return current_row_idx

        if choice == "前":
            self.tts.say("前")
            self.tts.runAndWait()
            new_idx = (current_row_idx - 1) % len(self.row_keys)
            return new_idx

        self.tts.say(choice)
        self.tts.runAndWait()

        if choice == "スペース":
            self.composed_sentence.append(" ")
        elif choice == "読み上げ":
            full_text = "".join(self.composed_sentence)
            self.tts.say(full_text if full_text else "空欄")
            self.tts.runAndWait()
        elif choice == "一文字消去":
            if self.composed_sentence:
                self.composed_sentence.pop()
        elif choice == "全消去":
            self.composed_sentence.clear()
        elif choice == "休止モード":
            self.execute_sleep_sequence()
        else:
            self.composed_sentence.append(choice)

        time.sleep(POST_SELECTION_RESET)
        return 0

    def execute_sleep_sequence(self):
        self.sleep_mode = True
        self.input_triggered.clear()
        self.snd_sleep.play()
        while self.sleep_mode and self.running:
            if self.input_triggered.is_set():
                self.snd_wake.play()
                self.tts.say("再開します")
                self.tts.runAndWait()
                self.sleep_mode = False
                self.input_triggered.clear()
            time.sleep(0.05)

    def start_engine(self):
        row_idx = 0
        while self.running:
            current_row_name = self.row_keys[row_idx]
            is_menu_bell = (current_row_name == "メニュー行")
            hit = self.speak_interruptible(current_row_name, is_bell=is_menu_bell)
            if not self.running:
                break
            if hit:
                tier_selection = None
                while tier_selection is None and self.running:
                    for char_opt in HIRAGANA_MATRIX[current_row_name]:
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
