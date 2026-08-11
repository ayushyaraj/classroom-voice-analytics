"""Background worker: one process-wide thread, one job at a time.

Single worker is deliberate: the ASR model holds around 1.5 GB resident and
two concurrent transcriptions would OOM a free tier box. Each stage persists
its output before the job row advances, so a crash mid-job resumes at the
failed stage instead of starting over. Partially transcribed chunks are
detected from the segments already in SQLite and skipped on resume.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from app import db
from app.asr.base import BaseTranscriber
from app.config import (
    DEFAULT_LANGUAGE,
    LANGUAGE_DETECT_CHUNKS,
    WORK_DIR,
)
from app.pipeline import metrics as metrics_mod
from app.pipeline import summary as summary_mod
from app.pipeline.chunker import Chunk, detect_speech_regions, plan_chunks, silence_gaps
from app.pipeline.preprocess import AudioError, preprocess, probe
from app.pipeline.speakers import attribute_speakers

logger = logging.getLogger(__name__)

# Poll interval for new jobs; cheap against SQLite, fast enough for a human
# watching the upload page.
POLL_SECONDS = 2.0

_transcribers: dict[str, BaseTranscriber] = {}


def _get_transcriber(model_size: str) -> BaseTranscriber:
    """Cache one transcriber per size for the life of the process.

    "groq" selects the cloud backend; every other value is a local
    faster-whisper model size.
    """
    if model_size not in _transcribers:
        if model_size == "groq":
            from app.asr.groq_backend import GroqCloudTranscriber

            _transcribers[model_size] = GroqCloudTranscriber()
        else:
            from app.asr.faster_whisper_backend import FasterWhisperTranscriber

            _transcribers[model_size] = FasterWhisperTranscriber(model_size)
    return _transcribers[model_size]


def _read_chunk(wav_path: Path, chunk: Chunk) -> np.ndarray:
    """Read exactly one chunk's samples; the file is never loaded whole."""
    with sf.SoundFile(wav_path) as f:
        start = int(chunk.start * f.samplerate)
        frames = int((chunk.end - chunk.start) * f.samplerate)
        f.seek(min(start, f.frames))
        audio = f.read(min(frames, f.frames - f.tell()), dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]
    return audio


# --- stages ---------------------------------------------------------------


def _stage_preprocess(conn, job: dict[str, Any]) -> None:
    audio_path = Path(job["audio_path"])
    info = probe(audio_path)
    wav_path = WORK_DIR / f"{job['id']}.wav"
    if not wav_path.exists():
        preprocess(audio_path, wav_path)
    db.update_job(
        conn,
        job["id"],
        wav_path=str(wav_path),
        duration_seconds=info["duration_seconds"],
        stage="preprocessing",
    )


def _detect_language_notice(
    conn,
    job: dict[str, Any],
    transcriber: BaseTranscriber,
    wav_path: Path,
    chunks: list[Chunk],
) -> str | None:
    """Detect language on the first speech chunks; never silently override
    the user's selection, only surface a notice."""
    votes: list[str] = []
    for chunk in chunks[:LANGUAGE_DETECT_CHUNKS]:
        audio = _read_chunk(wav_path, chunk)
        lang, prob = transcriber.detect_language(audio)
        votes.append(lang)
        logger.info(
            "job %s chunk at %.0fs detected language %s (%.2f)",
            job["id"], chunk.start, lang, prob,
        )
        del audio
    if not votes:
        return None
    detected, count = Counter(votes).most_common(1)[0]
    db.update_job(conn, job["id"], detected_language=detected)
    selected = job["language"]
    if selected not in ("auto", detected):
        return (
            f"You selected '{selected}' but the first chunks sound like "
            f"'{detected}' ({count} of {len(votes)} chunks). Transcription "
            f"continues in '{selected}'."
        )
    return None


def _stage_transcribe(conn, job: dict[str, Any]) -> None:
    wav_path = Path(job["wav_path"])
    duration = job["duration_seconds"] or 1.0

    regions = detect_speech_regions(wav_path)
    if not regions:
        raise AudioError("No speech was detected in the recording.")
    chunks = plan_chunks(regions)
    gaps = silence_gaps(regions, duration)
    # persisted now so analysis and later recomputes never re-run VAD
    db.save_metrics(conn, job["id"], {"silence_gaps": gaps})

    transcriber = _get_transcriber(job["model_size"])
    db.update_job(conn, job["id"], compute_type=transcriber.compute_type)

    notice = _detect_language_notice(conn, job, transcriber, wav_path, chunks)
    if notice:
        db.update_job(conn, job["id"], language_notice=notice)

    language = None if job["language"] == "auto" else job["language"]

    # resume support: skip chunks already fully covered by stored segments
    row = conn.execute(
        "SELECT MAX(end) AS last_end FROM segments WHERE job_id = ?",
        (job["id"],),
    ).fetchone()
    resume_from = (row["last_end"] or 0.0) + 0.5
    trailing_text = ""

    for chunk in chunks:
        if chunk.end <= resume_from:
            continue
        audio = _read_chunk(wav_path, chunk)
        # the previous chunk's trailing sentence keeps continuity across cuts
        prompt = trailing_text[-200:] if trailing_text else None
        segments = transcriber.transcribe_chunk(audio, language, prompt)
        del audio

        rows = [
            {
                "start": round(chunk.start + s.start, 2),
                "end": round(chunk.start + s.end, 2),
                "text": s.text,
                "features": {"avg_logprob": round(s.avg_logprob, 3)},
            }
            for s in segments
        ]
        if rows:
            db.insert_segments(conn, job["id"], rows)
            trailing_text = rows[-1]["text"]
        # real progress: seconds of audio processed over total seconds
        db.update_job(conn, job["id"], progress=min(chunk.end / duration, 1.0))

    db.update_job(conn, job["id"], stage="transcribing", progress=1.0)


def _stage_analyze(conn, job: dict[str, Any]) -> None:
    segments = db.get_segments(conn, job["id"])
    wav_path = Path(job["wav_path"])

    updates, corrections = attribute_speakers(wav_path, segments)
    by_id = {u["id"]: u for u in updates}
    for seg in segments:
        u = by_id.get(seg["id"])
        if u:
            seg["speaker"] = u["speaker"]
            seg["speaker_confidence"] = u["speaker_confidence"]
            seg["speaker_source"] = u["speaker_source"]

    stored = db.get_metrics(conn, job["id"])
    gaps = stored.get("silence_gaps", [])
    results = metrics_mod.analyze(
        segments, gaps, job["duration_seconds"] or 0.0, job["student_count"]
    )

    # push question flags and labels back to the segment rows
    db.update_segment_labels(
        conn,
        job["id"],
        [
            {
                "id": seg["id"],
                "speaker": seg.get("speaker"),
                "speaker_confidence": seg.get("speaker_confidence"),
                "speaker_source": seg.get("speaker_source"),
                "is_question": seg.get("is_question", False),
            }
            for seg in segments
        ],
    )
    # feature payloads are stored separately to keep the label update cheap
    conn.executemany(
        "UPDATE segments SET features = ? WHERE id = ? AND job_id = ?",
        [
            (json.dumps(by_id[sid]["features"]), sid, job["id"])
            for sid in by_id
        ],
    )
    conn.commit()

    meta_row = db.get_session_metadata(conn, job["id"])
    metadata = meta_row["data"] if meta_row else {}
    if metadata.get("student_count") is None and job["student_count"]:
        metadata["student_count"] = job["student_count"]
    results["summary"] = summary_mod.build_summary(
        results, metadata, job["duration_seconds"]
    )
    results["speaker_corrections"] = corrections
    results["silence_gaps"] = gaps
    db.save_metrics(conn, job["id"], results)
    db.update_job(conn, job["id"], stage="analyzing")


STAGES = (
    ("preprocessing", _stage_preprocess),
    ("transcribing", _stage_transcribe),
    ("analyzing", _stage_analyze),
)


def process_job(conn, job: dict[str, Any]) -> None:
    completed = job["stage"]
    stage_names = [name for name, _ in STAGES]
    start_index = stage_names.index(completed) + 1 if completed in stage_names else 0

    for name, fn in STAGES[start_index:]:
        db.set_status(conn, job["id"], name)
        stage_start = time.time()
        try:
            fn(conn, db.get_job(conn, job["id"]))
        except AudioError as exc:
            db.fail_job(conn, job["id"], name, str(exc))
            logger.warning("job %s failed in %s: %s", job["id"], name, exc)
            return
        except Exception as exc:
            logger.error(
                "job %s crashed in %s:\n%s", job["id"], name, traceback.format_exc()
            )
            message = _friendly_error(name, exc)
            db.fail_job(conn, job["id"], name, message)
            return
        logger.info(
            "job %s stage %s done in %.1fs", job["id"], name, time.time() - stage_start
        )
    db.set_status(conn, job["id"], "done")


def _friendly_error(stage: str, exc: Exception) -> str:
    """Map unexpected exceptions to a message a teacher trainer can act on.
    The stack trace goes to the log, never to the user."""
    text = str(exc).lower()
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "The server ran out of disk space while processing."
    if "connection" in text or "download" in text or "resolve" in text:
        return (
            "The speech model could not be downloaded. This happens on the "
            "first run without internet access. Retry once online."
        )
    return f"Processing failed during {stage}. The details are in the server log."


def worker_loop(stop_event: threading.Event) -> None:
    conn = db.connect()
    logger.info("worker started")
    while not stop_event.is_set():
        job = db.next_queued_job(conn)
        if job is None:
            stop_event.wait(POLL_SECONDS)
            continue
        logger.info(
            "picking up job %s (%s, status %s)",
            job["id"], job["original_filename"], job["status"],
        )
        process_job(conn, job)
    conn.close()


def start_worker() -> threading.Event:
    """Start the singleton worker thread; returns the stop event."""
    stop_event = threading.Event()
    thread = threading.Thread(target=worker_loop, args=(stop_event,), daemon=True)
    thread.start()
    return stop_event
