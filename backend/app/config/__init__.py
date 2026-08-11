"""Central configuration. Every threshold lives here with a reason.

The brief asked for app/config.py, but a config.py module cannot coexist with
the app/config/ package that holds lexicons.py (the package shadows the module),
so the thresholds live in the package __init__ instead. Imports read the same:
from app.config import RESPONSE_WINDOW_SECONDS.
"""

from pathlib import Path

# --- paths -----------------------------------------------------------------

# Repo root is three parents up from this file (app/config/__init__.py).
ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
WORK_DIR = DATA_DIR / "work"
ATTACHMENT_DIR = DATA_DIR / "attachments"
DB_PATH = DATA_DIR / "jobs.db"

# --- upload ------------------------------------------------------------------

# 500 MB: a two hour field recording at 128 kbps is about 115 MB, so this is
# roughly 4x headroom without letting someone fill the disk in one request.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
# 1 MB chunks keep memory flat while streaming a large upload to disk.
UPLOAD_CHUNK_BYTES = 1024 * 1024

# --- preprocessing -----------------------------------------------------------

# Whisper and silero-vad both expect 16 kHz mono.
TARGET_SAMPLE_RATE = 16000
# 80 Hz high pass: ceiling fan rumble and handling noise sit below this, while
# even a deep male voice keeps its fundamental above roughly 85 Hz.
HIGHPASS_HZ = 80

# --- voice activity detection ------------------------------------------------

# silero default speech probability threshold; raising it drops soft student
# murmur that we actually want to keep, lowering it lets fan noise in.
VAD_THRESHOLD = 0.5
# Ignore blips shorter than 250 ms, they are chair scrapes and clicks.
VAD_MIN_SPEECH_MS = 250
# A gap must be at least 300 ms to end a speech region, so mid-sentence
# breathing pauses do not fragment segments.
VAD_MIN_SILENCE_MS = 300
# Pad each speech region by 100 ms so word onsets are not clipped.
VAD_SPEECH_PAD_MS = 100

# --- chunking ----------------------------------------------------------------

# 30 to 60 second windows: long enough for Whisper to use context, short enough
# to keep per-chunk memory small and progress updates frequent. Cuts always
# happen at a VAD silence boundary so no word is split.
CHUNK_MIN_SECONDS = 30.0
CHUNK_MAX_SECONDS = 60.0

# --- transcription -----------------------------------------------------------

DEFAULT_MODEL_SIZE = "medium"
SUPPORTED_MODEL_SIZES = ("tiny", "base", "small", "medium")
DEFAULT_LANGUAGE = "mr"
SUPPORTED_LANGUAGES = ("mr", "hi", "en", "auto")
# Language detection runs on the first N speech chunks to compare against the
# user's selection; 3 keeps the check cheap while smoothing over one odd chunk.
LANGUAGE_DETECT_CHUNKS = 3

# --- silence classification ----------------------------------------------------

# 1.5 to 5 s reads as a natural pause (writing a word on the board, waiting for
# a hand). Above 5 s in a classroom recording usually means written work or a
# recorder left running, which a trainer wants flagged separately.
SHORT_PAUSE_MIN_SECONDS = 1.5
LONG_PAUSE_MIN_SECONDS = 5.0

# --- speaker attribution -------------------------------------------------------

# A student reply is only counted as a response if it starts within this many
# seconds of a teacher question ending. 8 s allows for classroom hesitation but
# excludes answers to a question asked minutes earlier.
RESPONSE_WINDOW_SECONDS = 8.0
# Choral response detection: short segments with near-identical text repeated
# across neighbours. 0.8 similarity tolerates ASR jitter between repetitions.
CHORAL_SIMILARITY = 0.8
# Choral answers are short; a 4 s ceiling stops full sentences matching.
CHORAL_MAX_SECONDS = 4.0
# How far (in segments) to look for a repeated choral phrase.
CHORAL_NEIGHBOUR_WINDOW = 3
# Lexicon-based label corrections need at least this much cue weight before
# they overturn the acoustic cluster, so one stray word does not flip a label.
LEXICON_OVERRIDE_WEIGHT = 2.0

# --- engagement metric bands ---------------------------------------------------

# Teacher Dominance Ratio: above 0.85 lecture heavy, 0.60-0.85 balanced,
# below 0.60 student led.
TDR_LECTURE_HEAVY = 0.85
TDR_BALANCED_FLOOR = 0.60
# Student Participation Indicator: below 0.20 low, 0.20-0.50 moderate, above high.
SPI_LOW_CEIL = 0.20
SPI_MODERATE_CEIL = 0.50
# Interaction Density (question-response pairs per minute): below 1 low
# dialogue, 1-3 active, above 3 highly interactive.
ID_LOW_CEIL = 1.0
ID_ACTIVE_CEIL = 3.0
