"""Question detection, talk time analysis, and the three engagement metrics.

Everything here is a pure function over segment dicts, so metrics recompute
identically after a manual speaker label flip in the UI.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from app.config import (
    ID_ACTIVE_CEIL,
    ID_LOW_CEIL,
    LONG_PAUSE_MIN_SECONDS,
    RESPONSE_WINDOW_SECONDS,
    SHORT_PAUSE_MIN_SECONDS,
    SPI_LOW_CEIL,
    SPI_MODERATE_CEIL,
    TDR_BALANCED_FLOOR,
    TDR_LECTURE_HEAVY,
)
from app.config.lexicons import NEGATIVE_FILTERS, all_question_words

TEACHER = "TEACHER"
STUDENT = "STUDENT"

_PUNCT = re.compile(r"[?.,!।।]+")


def _question_pattern() -> re.Pattern[str]:
    escaped = sorted((re.escape(p) for p in all_question_words()), key=len, reverse=True)
    joined = "|".join(escaped)
    # \b misbehaves around Devanagari, so boundaries are whitespace,
    # punctuation, or string edges.
    return re.compile(rf"(?:(?<=^)|(?<=[\s,.?!।]))(?:{joined})(?=$|[\s,.?!।])")


_QUESTION_RE = _question_pattern()


def _is_bare_filler(text: str) -> bool:
    """True when the segment is essentially just a filler phrase used as
    verbal punctuation ('theek hai', 'barobar'), which must not count as a
    question even though it can contain a question word."""
    normalized = _PUNCT.sub(" ", text.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if not normalized:
        return True
    for filler in NEGATIVE_FILTERS:
        if normalized == filler:
            return True
        # 0.85 tolerates ASR jitter like 'thik hai' vs 'theek hai'
        if SequenceMatcher(None, normalized, filler).ratio() >= 0.85:
            return True
    return False


def is_question(text: str) -> bool:
    """A segment is a question when it carries a question word or a question
    mark, and is not a bare filler."""
    if _is_bare_filler(text):
        return False
    if "?" in text:
        return True
    return bool(_QUESTION_RE.search(text.lower()))


def mark_questions(segments: list[dict[str, Any]]) -> None:
    """Set is_question in place. Only teacher segments count as questions for
    the engagement metrics; a student asking back is real but is not what
    teacher_question_count measures."""
    for seg in segments:
        seg["is_question"] = seg.get("speaker") == TEACHER and is_question(
            seg["text"]
        )


# --- engagement metrics -----------------------------------------------------


def teacher_dominance_ratio(
    teacher_talk_seconds: float, total_speech_seconds: float
) -> float:
    """Teacher Dominance Ratio.

    Formula: teacher_talk_seconds / total_speech_seconds.

    Of all the time anyone was speaking, how much was the teacher. It ignores
    silence entirely, so a quiet written-work classroom is not misread as
    teacher dominated.

    Interpretation: above 0.85 lecture heavy, 0.60 to 0.85 balanced,
    below 0.60 student led.
    """
    if total_speech_seconds <= 0:
        return 0.0
    return teacher_talk_seconds / total_speech_seconds


def student_participation_indicator(
    student_response_count: int,
    teacher_question_count: int,
    student_talk_seconds: float,
    total_speech_seconds: float,
) -> float:
    """Student Participation Indicator.

    Formula: (student_response_count / max(teacher_question_count, 1))
             * (student_talk_seconds / total_speech_seconds), clamped to 0..1.

    The first factor asks whether questions get answered, the second whether
    students actually get airtime. Multiplying them stops choral one word
    replies from scoring like students explaining their reasoning: many
    answers with near-zero airtime still scores low.

    Interpretation: below 0.20 low, 0.20 to 0.50 moderate, above 0.50 high.
    """
    if total_speech_seconds <= 0:
        return 0.0
    answer_rate = student_response_count / max(teacher_question_count, 1)
    airtime = student_talk_seconds / total_speech_seconds
    return max(0.0, min(1.0, answer_rate * airtime))


def interaction_density(
    qa_pair_count: int, duration_seconds: float
) -> float:
    """Interaction Density.

    Formula: question-response turn pairs / duration in minutes.

    A pair is one teacher question that received at least one student
    response inside the response window. Dividing by duration makes a 20
    minute and a 90 minute recording comparable.

    Interpretation: below 1 per minute low dialogue, 1 to 3 active,
    above 3 highly interactive.
    """
    if duration_seconds <= 0:
        return 0.0
    return qa_pair_count / (duration_seconds / 60.0)


def tdr_band(value: float) -> str:
    if value > TDR_LECTURE_HEAVY:
        return "lecture heavy"
    if value >= TDR_BALANCED_FLOOR:
        return "balanced"
    return "student led"


def spi_band(value: float) -> str:
    if value < SPI_LOW_CEIL:
        return "low"
    if value <= SPI_MODERATE_CEIL:
        return "moderate"
    return "high"


def id_band(value: float) -> str:
    if value < ID_LOW_CEIL:
        return "low dialogue"
    if value <= ID_ACTIVE_CEIL:
        return "active"
    return "highly interactive"


# --- full analysis -----------------------------------------------------------


def _responses_and_pairs(
    segments: list[dict[str, Any]]
) -> tuple[int, int]:
    """Count student responses and question-response pairs.

    A response is a student segment starting within RESPONSE_WINDOW_SECONDS
    of a teacher question ending. A pair is a question with at least one
    response; a burst of choral answers to one question is one pair.
    """
    questions = [s for s in segments if s.get("is_question")]
    students = [s for s in segments if s.get("speaker") == STUDENT]
    response_ids: set[int] = set()
    pair_count = 0
    for q in questions:
        answered = False
        for s in students:
            if q["end"] <= s["start"] <= q["end"] + RESPONSE_WINDOW_SECONDS:
                response_ids.add(id(s))
                answered = True
            elif s["start"] > q["end"] + RESPONSE_WINDOW_SECONDS:
                break
        if answered:
            pair_count += 1
    return len(response_ids), pair_count


def _timeline(
    segments: list[dict[str, Any]], duration_seconds: float
) -> list[dict[str, float]]:
    """Per minute teacher/student speech seconds for the activity strip."""
    minutes = int(duration_seconds // 60) + (1 if duration_seconds % 60 else 0)
    timeline = [
        {"minute": m, "teacher_seconds": 0.0, "student_seconds": 0.0}
        for m in range(max(minutes, 1))
    ]
    for seg in segments:
        key = (
            "teacher_seconds"
            if seg.get("speaker") == TEACHER
            else "student_seconds"
        )
        start, end = seg["start"], seg["end"]
        m = int(start // 60)
        while start < end and m < len(timeline):
            boundary = min(end, (m + 1) * 60.0)
            timeline[m][key] += boundary - start
            start = boundary
            m += 1
    for row in timeline:
        row["teacher_seconds"] = round(row["teacher_seconds"], 1)
        row["student_seconds"] = round(row["student_seconds"], 1)
    return timeline


def analyze(
    segments: list[dict[str, Any]],
    silence_gaps: list[float],
    duration_seconds: float,
    student_count: int | None,
) -> dict[str, Any]:
    """Compute every persisted metric from labelled segments.

    Called both after transcription and after any manual label flip, so it
    must stay pure: same inputs, same numbers.
    """
    mark_questions(segments)

    teacher_talk = sum(
        s["end"] - s["start"] for s in segments if s.get("speaker") == TEACHER
    )
    student_talk = sum(
        s["end"] - s["start"] for s in segments if s.get("speaker") == STUDENT
    )
    total_speech = teacher_talk + student_talk

    question_count = sum(1 for s in segments if s.get("is_question"))
    response_count, pair_count = _responses_and_pairs(segments)

    short_pause = sum(
        g for g in silence_gaps
        if SHORT_PAUSE_MIN_SECONDS <= g < LONG_PAUSE_MIN_SECONDS
    )
    long_pause = sum(g for g in silence_gaps if g >= LONG_PAUSE_MIN_SECONDS)

    tdr = teacher_dominance_ratio(teacher_talk, total_speech)
    spi = student_participation_indicator(
        response_count, question_count, student_talk, total_speech
    )
    density = interaction_density(pair_count, duration_seconds)

    per_student = (
        round(student_talk / student_count, 1)
        if student_count and student_count > 0
        else None
    )

    return {
        "teacher_talk_seconds": round(teacher_talk, 1),
        "student_talk_seconds": round(student_talk, 1),
        "total_speech_seconds": round(total_speech, 1),
        "teacher_talk_percent": round(100 * teacher_talk / total_speech, 1)
        if total_speech
        else 0.0,
        "student_talk_percent": round(100 * student_talk / total_speech, 1)
        if total_speech
        else 0.0,
        "teacher_question_count": question_count,
        "student_response_count": response_count,
        "qa_pair_count": pair_count,
        "short_pause_seconds": round(short_pause, 1),
        "long_pause_seconds": round(long_pause, 1),
        "teacher_dominance_ratio": round(tdr, 3),
        "teacher_dominance_band": tdr_band(tdr),
        "student_participation_indicator": round(spi, 3),
        "student_participation_band": spi_band(spi),
        "interaction_density": round(density, 3),
        "interaction_density_band": id_band(density),
        "per_student_talk_seconds": per_student,
        "timeline": _timeline(segments, duration_seconds),
    }
