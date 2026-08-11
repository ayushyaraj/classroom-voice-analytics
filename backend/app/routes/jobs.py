"""Job API routes. Handlers stay thin: parse, delegate, shape the response.
All real work lives in app.ingest, app.db, and app.pipeline."""

from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from app import db, ingest
from app.config import SUPPORTED_LANGUAGES, SUPPORTED_MODEL_SIZES
from app.pipeline import metrics as metrics_mod
from app.pipeline import summary as summary_mod

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _conn():
    return db.connect()


def _job_or_404(conn, job_id: str) -> dict:
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("")
async def create_job(
    audio: UploadFile = File(...),
    sidecar: UploadFile | None = File(None),
    photo: UploadFile | None = File(None),
    language: str = Form("mr"),
    model_size: str = Form("medium"),
    student_count: int | None = Form(None),
):
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported language.")
    if model_size not in SUPPORTED_MODEL_SIZES:
        raise HTTPException(status_code=422, detail="Unsupported model size.")
    conn = _conn()
    try:
        job_id, warnings = await ingest.create_job_from_upload(
            conn, audio, sidecar, photo, language, model_size, student_count
        )
    except ingest.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"job_id": job_id, "status": "queued", "warnings": warnings}


@router.get("/demo/id")
def demo_id():
    """Job id of the pre-computed demo result, if one was baked in at build
    time. Free tier CPU makes a live one hour upload slow, so reviewers get
    a finished result instantly while live upload keeps working."""
    marker = Path(db.DB_PATH).parent / "demo_job_id.txt"
    if marker.exists():
        return {"job_id": marker.read_text(encoding="utf-8").strip()}
    return {"job_id": None}


@router.get("/{job_id}")
def get_job(job_id: str):
    conn = _conn()
    try:
        job = _job_or_404(conn, job_id)
        segments = db.get_segments(conn, job_id)
        metrics = db.get_metrics(conn, job_id)
        metadata = db.get_session_metadata(conn, job_id)
    finally:
        conn.close()
    job["warnings"] = json.loads(job["warnings"]) if job["warnings"] else []
    job.pop("audio_path", None)
    job.pop("wav_path", None)
    has_photo = bool(job.pop("photo_path", None))
    return {
        "job": job,
        "has_photo": has_photo,
        "segments": segments,
        "metrics": metrics,
        "metadata": metadata,
    }


@router.get("/{job_id}/progress")
def get_progress(job_id: str):
    conn = _conn()
    try:
        job = _job_or_404(conn, job_id)
        segment_count = conn.execute(
            "SELECT COUNT(*) AS n FROM segments WHERE job_id = ?", (job_id,)
        ).fetchone()["n"]
    finally:
        conn.close()
    return {
        "status": job["status"],
        "stage": job["status"],
        "progress": job["progress"],
        "error": job["error"],
        "error_stage": job["error_stage"],
        "elapsed_seconds": round(time.time() - job["created_at"], 1),
        "segment_count": segment_count,
        "language_notice": job["language_notice"],
        "detected_language": job["detected_language"],
    }


@router.get("/{job_id}/segments")
def get_segments(job_id: str, after_id: int = 0):
    """Incremental fetch for the partial transcript during processing."""
    conn = _conn()
    try:
        _job_or_404(conn, job_id)
        rows = conn.execute(
            """SELECT id, start, end, text, speaker, speaker_confidence,
                      speaker_source, is_question
               FROM segments WHERE job_id = ? AND id > ? ORDER BY id""",
            (job_id, after_id),
        ).fetchall()
    finally:
        conn.close()
    return {"segments": [dict(r) for r in rows]}


class LabelFlip(BaseModel):
    segment_id: int
    speaker: str


@router.patch("/{job_id}/segments")
def flip_labels(job_id: str, flips: list[LabelFlip]):
    """Apply manual speaker corrections and recompute every metric."""
    if any(f.speaker not in ("TEACHER", "STUDENT") for f in flips):
        raise HTTPException(status_code=422, detail="Speaker must be TEACHER or STUDENT.")
    conn = _conn()
    try:
        job = _job_or_404(conn, job_id)
        db.update_segment_labels(
            conn,
            job_id,
            [
                {
                    "id": f.segment_id,
                    "speaker": f.speaker,
                    "speaker_confidence": 1.0,  # a human said so
                    "speaker_source": "manual",
                }
                for f in flips
            ],
        )
        segments = db.get_segments(conn, job_id)
        stored = db.get_metrics(conn, job_id)
        results = metrics_mod.analyze(
            segments,
            stored.get("silence_gaps", []),
            job["duration_seconds"] or 0.0,
            job["student_count"],
        )
        db.update_segment_labels(
            conn,
            job_id,
            [
                {
                    "id": s["id"],
                    "speaker": s.get("speaker"),
                    "speaker_confidence": s.get("speaker_confidence"),
                    "speaker_source": s.get("speaker_source"),
                    "is_question": s.get("is_question", False),
                }
                for s in segments
            ],
        )
        meta_row = db.get_session_metadata(conn, job_id)
        metadata = meta_row["data"] if meta_row else {}
        results["summary"] = summary_mod.build_summary(
            results, metadata, job["duration_seconds"]
        )
        results["silence_gaps"] = stored.get("silence_gaps", [])
        db.save_metrics(conn, job_id, results)
        metrics = db.get_metrics(conn, job_id)
    finally:
        conn.close()
    return {"metrics": metrics}


@router.get("/{job_id}/photo")
def get_photo(job_id: str):
    conn = _conn()
    try:
        job = _job_or_404(conn, job_id)
    finally:
        conn.close()
    if not job["photo_path"] or not Path(job["photo_path"]).exists():
        raise HTTPException(status_code=404, detail="No photo attached.")
    return FileResponse(job["photo_path"])


def _timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@router.get("/{job_id}/transcript.txt")
def transcript_txt(job_id: str):
    conn = _conn()
    try:
        _job_or_404(conn, job_id)
        segments = db.get_segments(conn, job_id)
    finally:
        conn.close()
    lines = [
        f"[{_timestamp(s['start'])} - {_timestamp(s['end'])}] "
        f"{s['speaker'] or 'UNKNOWN'}: {s['text']}"
        for s in segments
    ]
    return PlainTextResponse(
        "\n".join(lines),
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}_transcript.txt"'
        },
    )


@router.get("/{job_id}/report.csv")
def report_csv(job_id: str):
    conn = _conn()
    try:
        _job_or_404(conn, job_id)
        segments = db.get_segments(conn, job_id)
    finally:
        conn.close()

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["start", "end", "speaker", "confidence", "source",
             "is_question", "text"]
        )
        for s in segments:
            writer.writerow(
                [
                    s["start"],
                    s["end"],
                    s["speaker"] or "",
                    s["speaker_confidence"] or "",
                    s["speaker_source"] or "",
                    int(s["is_question"]),
                    s["text"],
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}_report.csv"'
        },
    )
