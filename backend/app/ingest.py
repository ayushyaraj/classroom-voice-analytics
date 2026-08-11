"""Upload ingestion: streaming file writes, validation, sidecar handling.

Lives outside the route handlers so the routes stay declarative and this
logic is unit-testable without HTTP.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import UploadFile

from app import db
from app.config import (
    ATTACHMENT_DIR,
    MAX_UPLOAD_BYTES,
    UPLOAD_CHUNK_BYTES,
    UPLOAD_DIR,
)
from app.metadata.loader import parse_metadata
from app.pipeline.preprocess import (
    AudioError,
    extension_matches_container,
    probe,
)

logger = logging.getLogger(__name__)


class UploadError(Exception):
    """User-presentable upload rejection."""


async def save_stream(upload: UploadFile, dest: Path) -> int:
    """Stream an upload to disk in fixed chunks; the request body is never
    held in memory. Raises UploadError past the size cap."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise UploadError(
                        f"File exceeds the {MAX_UPLOAD_BYTES // (1024*1024)} MB "
                        "upload limit."
                    )
                out.write(chunk)
    except UploadError:
        dest.unlink(missing_ok=True)
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        if getattr(exc, "errno", None) == 28:
            raise UploadError("The server is out of disk space.") from exc
        raise UploadError("The file could not be saved.") from exc
    return written


async def create_job_from_upload(
    conn,
    audio: UploadFile,
    sidecar: UploadFile | None,
    photo: UploadFile | None,
    language: str,
    model_size: str,
    student_count: int | None,
) -> tuple[str, list[str]]:
    """Persist the upload triplet, validate the audio, create the job row.

    Returns (job_id, warnings). Raises UploadError with a clear message when
    the audio itself is unusable; sidecar and photo problems are warnings,
    never rejections.
    """
    warnings: list[str] = []
    original_name = audio.filename or "recording"
    base_name = Path(original_name).stem

    staging = UPLOAD_DIR / f"staging_{base_name}{Path(original_name).suffix}"
    await save_stream(audio, staging)

    try:
        info = probe(staging)
    except AudioError as exc:
        staging.unlink(missing_ok=True)
        raise UploadError(str(exc)) from exc

    if not extension_matches_container(staging, info["container"] or ""):
        # warn, do not reject: the real field app writes MP4 audio as .mp3
        warnings.append(
            f"The file extension does not match its container "
            f"({info['container']}). Processing continues on the probed format."
        )

    # sidecar metadata: missing means empty, malformed means warning
    metadata = None
    unmapped: list[str] = []
    meta_warnings: list[str] = []
    if sidecar is not None and sidecar.filename:
        raw_bytes = await sidecar.read()
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
            metadata, unmapped, meta_warnings = parse_metadata(
                raw, base_name=base_name
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            meta_warnings = [f"sidecar JSON could not be parsed: {exc}"]

    if student_count is None and metadata is not None:
        student_count = metadata.student_count

    photo_path: Path | None = None
    if photo is not None and photo.filename:
        suffix = Path(photo.filename).suffix or ".jpg"
        photo_path = ATTACHMENT_DIR / f"{base_name}{suffix}"
        await save_stream(photo, photo_path)

    job_id = db.create_job(
        conn,
        original_filename=original_name,
        audio_path=str(staging),
        language=language,
        model_size=model_size,
        student_count=student_count,
        photo_path=str(photo_path) if photo_path else None,
    )

    # move staging under the job id so concurrent uploads of the same
    # filename cannot collide
    final = UPLOAD_DIR / f"{job_id}{Path(original_name).suffix}"
    staging.rename(final)
    db.update_job(conn, job_id, audio_path=str(final))

    if metadata is not None or meta_warnings:
        db.save_session_metadata(
            conn,
            job_id,
            metadata.to_dict() if metadata else {},
            unmapped,
            meta_warnings,
        )
        for key in unmapped:
            logger.info("job %s sidecar key not mapped: %s", job_id, key)

    for w in warnings + meta_warnings:
        db.add_warning(conn, job_id, w)
    return job_id, warnings + meta_warnings
