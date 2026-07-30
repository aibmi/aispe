# mojiban — shared configuration
# These values match the "Global Timing & Threshold Constants" table in the
# Master Integration Blueprint. Change them here — nowhere else — and every
# file picks up the new value.

# --- Timing ---
SCAN_WINDOW_TIMEOUT = 3.0     # seconds the voice waits after speaking an option
POST_SELECTION_RESET = 1.0    # seconds of pause before scanning restarts at あ行
HARDWARE_DEBOUNCE = 0.4       # seconds to ignore repeat clicks/twitches after one hit

# --- Motor Imagery (EEG) ---
# C3 vs C4 lateralization index: (C4_power - C3_power) / (C4_power + C3_power).
# Near 0 at rest; rises when C3 desyncs during right-hand motor imagery.
MI_LATERALIZATION_DELTA = 0.15   # trigger when index rises this far above its own baseline
MI_SAMPLING_WINDOW_SEC = 2.0     # seconds of EEG history used per power calculation
MI_REFRACTORY_SEC = 1.5          # seconds to ignore new triggers right after a detected pulse

# Kept for the single-channel fallback path (used only if C4 isn't wired yet).
MI_POWER_THRESHOLD = 0.45

# --- Voice ---
TTS_VOICE_RATE = 135          # words per minute

# --- Caregiver display colors ---
COLOR_BACKGROUND = "#000000"
COLOR_TEXT_STANDARD = "#00FF00"
COLOR_TEXT_ACTIVE = "#FFB300"
COLOR_FLASH_RECEIVED = "#FF0000"
COLOR_SLEEP_TEXT = "#4A4A4A"
COLOR_SLEEP_STANDBY = "#4A90E2"
