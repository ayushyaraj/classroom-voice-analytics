"""Audio probing and preprocessing via ffmpeg subprocesses.

The whole file is never loaded into Python memory; ffmpeg streams from disk
to disk. Resampling to 16 kHz mono happens first so the high pass is cheap:

    ffmpeg -i input -af aresample=16000,highpass=f=80
           -ac 1 -ar 16000 -sample_fmt s16 -y output.wav

    aresample=16000 resample early so the high pass processes fewer samples
    highpass=f=80   cuts ceiling fan rumble below the voice band
    -ac 1 -ar 16000 mono 16 kHz, what Whisper and silero-vad expect
    -sample_fmt s16 16 bit PCM

I dropped level normalization (loudnorm, then dynaudnorm) because it was the
slow filter on a small free-tier box, and the ASR models handle level fine.
Keeping raw levels also helps the energy based speaker heuristic.
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


def preprocess(
    input_path: Path,
    output_wav: Path,
    total_seconds: float | None = None,
    progress_cb=None,
) -> str:
    """Convert input to analysis-ready wav in one ffmpeg pass.

    Only two cheap filters run: resample to 16 kHz (done first, so the rest is
    cheap) and an 80 Hz high pass for fan rumble. Level normalization was
    dropped because it was the slow filter on a small box and the ASR models
    are robust to level. If total_seconds and progress_cb are given, ffmpeg's
    own progress is streamed so the UI bar moves during conversion instead of
    sitting at zero.

    Returns the exact command string that ran, for the job log and README.
    """
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _binary("ffmpeg"),
        "-i", str(input_path),
        "-af", f"aresample={TARGET_SAMPLE_RATE},highpass=f={HIGHPASS_HZ}",
        "-ac", "1",
        "-ar", str(TARGET_SAMPLE_RATE),
        "-sample_fmt", "s16",
        "-progress", "pipe:1",
        "-nostats",
        "-y",
        str(output_wav),
    ]
    logger.info("preprocess: %s", " ".join(cmd))

    # Stream stdout so the -progress lines can drive the UI bar. stderr is kept
    # for the error message if it fails.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        for line in proc.stdout:
            if progress_cb and total_seconds and line.startswith("out_time_us="):
                raw = line.strip().split("=", 1)[1]
                if raw.isdigit():
                    frac = min(int(raw) / 1_000_000 / total_seconds, 0.999)
                    progress_cb(frac)
        proc.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AudioError("Audio conversion timed out.")

    if proc.returncode != 0:
        tail = (proc.stderr.read() or "").strip().splitlines()[-3:]
        logger.warning("ffmpeg failed: %s", " | ".join(tail))
        raise AudioError(
            "Audio conversion failed. The file may use an unsupported codec."
        )
    if not output_wav.exists() or output_wav.stat().st_size == 0:
        raise AudioError("Audio conversion produced no output.")
    if progress_cb:
        progress_cb(1.0)
    return " ".join(cmd)
