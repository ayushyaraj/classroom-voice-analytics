"""Heuristic teacher/student attribution. This is approximation, not
diarization, and is labelled as such in the UI and README.

Per segment acoustic features (median F0, RMS energy, duration, word count,
speech rate) feed a two cluster KMeans. The cluster holding the larger share
of total speech time is labelled TEACHER, because teacher talk dominates
nearly every real classroom recording. Lexicon cues then correct individual
segments, and near-identical short phrases repeated across neighbours are
forced to STUDENT because choral response is how these classrooms answer.

Every correction is logged and returned so the logic is auditable, and the
UI can flip any label, after which metrics recompute.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf
from sklearn.cluster import KMeans

from app.config import (
    CHORAL_MAX_SECONDS,
    CHORAL_NEIGHBOUR_WINDOW,
    CHORAL_SIMILARITY,
    LEXICON_OVERRIDE_WEIGHT,
    TARGET_SAMPLE_RATE,
)
from app.config.lexicons import all_student_cues, all_teacher_cues

logger = logging.getLogger(__name__)

TEACHER = "TEACHER"
STUDENT = "STUDENT"

# Voiced F0 search band: 65 Hz reaches a deep adult male voice, 400 Hz covers
# a child's speaking pitch. Anything outside is not a speaking fundamental.
F0_MIN = 65.0
F0_MAX = 400.0


def _word_boundary_pattern(phrases: list[str]) -> re.Pattern[str]:
    escaped = sorted((re.escape(p) for p in phrases), key=len, reverse=True)
    # \b fails around Devanagari, so match on non-word-or-space boundaries
    # manually via lookarounds on whitespace/punctuation/string edges.
    joined = "|".join(escaped)
    return re.compile(rf"(?:(?<=^)|(?<=[\s,.?!।]))(?:{joined})(?=$|[\s,.?!।])")


_TEACHER_RE = _word_boundary_pattern(all_teacher_cues())
_STUDENT_RE = _word_boundary_pattern(all_student_cues())


def extract_features(wav_path: Path, segments: list[dict[str, Any]]) -> np.ndarray:
    """Per segment: [median F0, RMS energy, duration, word count, speech rate].

    Reads only each segment's samples from disk, so memory stays flat on a
    two hour file.
    """
    rows: list[list[float]] = []
    with sf.SoundFile(wav_path) as f:
        sr = f.samplerate
        for seg in segments:
            start_frame = int(seg["start"] * sr)
            n_frames = max(int((seg["end"] - seg["start"]) * sr), 1)
            f.seek(min(start_frame, f.frames))
            audio = f.read(min(n_frames, f.frames - f.tell()), dtype="float32")
            if audio.ndim > 1:
                audio = audio[:, 0]

            duration = max(seg["end"] - seg["start"], 1e-3)
            words = len(seg["text"].split())
            rate = words / duration

            if len(audio) < 512:
                rows.append([0.0, 0.0, duration, float(words), rate])
                continue

            rms = float(np.sqrt(np.mean(audio**2)))
            pitches, magnitudes = librosa.piptrack(
                y=audio, sr=sr, fmin=F0_MIN, fmax=F0_MAX, n_fft=1024
            )
            # per frame, take the pitch at the strongest bin; keep voiced ones
            best = magnitudes.argmax(axis=0)
            frame_pitch = pitches[best, np.arange(pitches.shape[1])]
            frame_mag = magnitudes[best, np.arange(magnitudes.shape[1])]
            voiced = frame_pitch[(frame_pitch > 0) & (frame_mag > 0)]
            f0 = float(np.median(voiced)) if voiced.size else 0.0

            rows.append([f0, rms, duration, float(words), rate])
            del audio
    return np.array(rows, dtype=np.float64)


def _cluster(features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two cluster KMeans on z-scored features.

    Returns (labels, confidence) where confidence is how much closer each
    point sits to its own centre than the other (0.5 ambiguous, 1.0 clear).
    """
    mean = features.mean(axis=0)
    std = features.std(axis=0)
    std[std == 0] = 1.0
    normed = (features - mean) / std

    km = KMeans(n_clusters=2, n_init=10, random_state=0)
    labels = km.fit_predict(normed)
    dists = np.linalg.norm(
        normed[:, None, :] - km.cluster_centers_[None, :, :], axis=2
    )
    own = dists[np.arange(len(labels)), labels]
    other = dists[np.arange(len(labels)), 1 - labels]
    confidence = other / np.maximum(own + other, 1e-9)
    return labels, confidence


def _cue_weight(text: str, pattern: re.Pattern[str]) -> float:
    return float(len(pattern.findall(text.lower())))


def _is_choral(
    idx: int, segments: list[dict[str, Any]]
) -> bool:
    """A short phrase repeated near-identically by an adjacent segment is a
    choral answer, the standard reply mode in these classrooms."""
    seg = segments[idx]
    duration = seg["end"] - seg["start"]
    if duration > CHORAL_MAX_SECONDS or not seg["text"].strip():
        return False
    lo = max(0, idx - CHORAL_NEIGHBOUR_WINDOW)
    hi = min(len(segments), idx + CHORAL_NEIGHBOUR_WINDOW + 1)
    for j in range(lo, hi):
        if j == idx:
            continue
        other = segments[j]
        if other["end"] - other["start"] > CHORAL_MAX_SECONDS:
            continue
        similarity = SequenceMatcher(
            None, seg["text"].lower().strip(), other["text"].lower().strip()
        ).ratio()
        if similarity >= CHORAL_SIMILARITY:
            return True
    return False


def attribute_speakers(
    wav_path: Path, segments: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Label each segment TEACHER or STUDENT.

    Returns (updates, correction_log). Each update carries the segment id,
    speaker, speaker_confidence, speaker_source, and the raw features so the
    UI can show why a segment was labelled the way it was.
    """
    if not segments:
        return [], []

    corrections: list[str] = []
    features = extract_features(wav_path, segments)

    if len(segments) < 4:
        # Too few points to cluster meaningfully; a near-empty recording is
        # almost always one person speaking.
        updates = [
            {
                "id": s["id"],
                "speaker": TEACHER,
                "speaker_confidence": 0.5,
                "speaker_source": "cluster",
                "features": _feature_dict(features[i]),
            }
            for i, s in enumerate(segments)
        ]
        corrections.append("fewer than 4 segments, defaulted all to TEACHER")
        return updates, corrections

    labels, confidence = _cluster(features)

    # the cluster with the larger share of speech time is the teacher
    durations = features[:, 2]
    time_c0 = durations[labels == 0].sum()
    time_c1 = durations[labels == 1].sum()
    teacher_cluster = 0 if time_c0 >= time_c1 else 1

    updates: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        speaker = TEACHER if labels[i] == teacher_cluster else STUDENT
        conf = float(confidence[i])
        source = "cluster"

        teacher_w = _cue_weight(seg["text"], _TEACHER_RE)
        student_w = _cue_weight(seg["text"], _STUDENT_RE)
        # lexicon cues overturn the acoustic label only past a weight margin,
        # so a single stray word cannot flip a segment
        if speaker == STUDENT and teacher_w - student_w >= LEXICON_OVERRIDE_WEIGHT:
            speaker, source, conf = TEACHER, "lexicon", max(conf, 0.6)
            corrections.append(
                f"segment {seg['id']} ({seg['start']:.1f}s) flipped to TEACHER, "
                f"teacher cue weight {teacher_w:.0f} vs student {student_w:.0f}"
            )
        elif speaker == TEACHER and student_w - teacher_w >= LEXICON_OVERRIDE_WEIGHT:
            speaker, source, conf = STUDENT, "lexicon", max(conf, 0.6)
            corrections.append(
                f"segment {seg['id']} ({seg['start']:.1f}s) flipped to STUDENT, "
                f"student cue weight {student_w:.0f} vs teacher {teacher_w:.0f}"
            )

        if speaker == TEACHER and _is_choral(i, segments):
            speaker, source, conf = STUDENT, "choral", 0.9
            corrections.append(
                f"segment {seg['id']} ({seg['start']:.1f}s) flipped to STUDENT, "
                "choral repetition"
            )

        updates.append(
            {
                "id": seg["id"],
                "speaker": speaker,
                "speaker_confidence": round(conf, 3),
                "speaker_source": source,
                "features": _feature_dict(features[i]),
            }
        )

    for line in corrections:
        logger.info("speaker correction: %s", line)
    return updates, corrections


def _feature_dict(row: np.ndarray) -> dict[str, float]:
    return {
        "f0_median": round(float(row[0]), 1),
        "rms": round(float(row[1]), 5),
        "duration": round(float(row[2]), 2),
        "words": float(row[3]),
        "speech_rate": round(float(row[4]), 2),
    }
