"""Audio probing and preprocessing via ffmpeg subprocesses.

The whole file is never loaded into Python memory; ffmpeg streams from disk
to disk. One ffmpeg invocation does every transform in a single pass:

    ffmpeg -i input -af highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11
           -ac 1 -ar 16000 -sample_fmt s16 -y output.wav

    highpass=f=80   cuts ceiling fan rumble below the voice band
    loudnorm        evens out varying teacher-to-phone distance
    -ac 1 -ar 16000 mono 16 kHz, what Whisper and silero-vad expect
    -sample_fmt s16 16 bit PCM
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from app.config import HIGHPASS_HZ, TARGET_SAMPLE_RATE

logger = logging.getLogger(__name__)


class AudioError(Exception):
    """Raised with a user-presentable message when input audio is unusable."""


def _binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise AudioError(
            f"{name} was not found on PATH. Install ffmpeg and restart."
        )
    return path


def probe(input_path: Path) -> dict:
    """Validate an uploaded file with ffprobe and return its audio facts.

    The container is probed, never trusted from the extension: the real field
    sample is AAC in an MP4 container carrying a .mp3 extension.
    """
    if not input_path.exists() or input_path.stat().st_size == 0:
        raise AudioError("The uploaded file is empty.")

    cmd = [
        _binary("ffprobe"),
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.warning("ffprobe failed: %s", result.stderr.strip())
        raise AudioError(
            "The file could not be read as audio. It may be corrupt or not "
            "an audio file at all."
        )

    info = json.loads(result.stdout or "{}")
    streams = [
        s for s in info.get("streams", []) if s.get("codec_type") == "audio"
    ]
    if not streams:
        raise AudioError("The file contains no audio stream.")

    fmt = info.get("format", {})
    duration = float(fmt.get("duration") or streams[0].get("duration") or 0)
    if duration <= 0:
        raise AudioError("The audio stream has zero length.")

    return {
        "duration_seconds": duration,
        "codec": streams[0].get("codec_name"),
        "container": fmt.get("format_name"),
        "sample_rate": int(streams[0].get("sample_rate") or 0),
        "channels": int(streams[0].get("channels") or 0),
        "size_bytes": int(fmt.get("size") or input_path.stat().st_size),
    }


def extension_matches_container(input_path: Path, container: str) -> bool:
    """True when the filename extension is consistent with the probed
    container. Used to warn, not reject: the field app writes MP4 audio with
    a .mp3 extension and those files must still process."""
    ext = input_path.suffix.lower().lstrip(".")
    names = container.split(",") if container else []
    equivalents = {
        "mp3": {"mp3"},
        "wav": {"wav"},
        "m4a": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
        "aac": {"aac"},
        "ogg": {"ogg"},
        "flac": {"flac"},
        "webm": {"matroska", "webm"},
        "mkv": {"matroska", "webm"},
    }
    allowed = equivalents.get(ext)
    if allowed is None:
        return False
    return any(name in allowed for name in names)


def preprocess(input_path: Path, output_wav: Path) -> str:
    """Convert input to analysis-ready wav in one ffmpeg pass.

    Returns the exact command string that ran, for the job log and README.
    """
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _binary("ffmpeg"),
        "-i", str(input_path),
        "-af", f"highpass=f={HIGHPASS_HZ},loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", "1",
        "-ar", str(TARGET_SAMPLE_RATE),
        "-sample_fmt", "s16",
        "-y",
        str(output_wav),
    ]
    logger.info("preprocess: %s", " ".join(cmd))
    # A two hour file transcodes in a few minutes on CPU; 30 min is a hard
    # stop against a hung process, not an expected duration.
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-3:]
        logger.warning("ffmpeg failed: %s", " | ".join(tail))
        raise AudioError(
            "Audio conversion failed. The file may use an unsupported codec."
        )
    if not output_wav.exists() or output_wav.stat().st_size == 0:
        raise AudioError("Audio conversion produced no output.")
    return " ".join(cmd)
