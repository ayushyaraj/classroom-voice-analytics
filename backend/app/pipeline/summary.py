"""Template driven session summary.

No LLM call: that would reintroduce an API key, which the whole design
avoids. Sentences vary by which interpretation band each metric landed in,
so two different lessons do not read like the same filled-in form.
"""

from __future__ import annotations

from typing import Any


def _mins(seconds: float | None) -> str:
    return f"{(seconds or 0) / 60:.0f} minutes"


def _opening(metadata: dict[str, Any], duration_seconds: float | None) -> str:
    place_bits = [
        metadata.get(k) for k in ("school_name", "village", "district", "state")
    ]
    place = ", ".join(str(b) for b in place_bits if b)
    grade = metadata.get("class_or_grade")
    subject = metadata.get("subject") or metadata.get("activity_type")
    teacher = metadata.get("teacher_name")

    lesson = "This recording"
    if subject and grade:
        lesson = f"This {subject} session with class {grade}"
    elif subject:
        lesson = f"This {subject} session"
    elif grade:
        lesson = f"This session with class {grade}"

    parts = [lesson]
    if place:
        parts.append(f"at {place}")
    if teacher:
        parts.append(f"led by {teacher}")
    return " ".join(parts) + f" runs {_mins(duration_seconds)}."


def _talk_sentence(m: dict[str, Any]) -> str:
    band = m["teacher_dominance_band"]
    tp = m["teacher_talk_percent"]
    sp = m["student_talk_percent"]
    if band == "lecture heavy":
        return (
            f"The teacher holds {tp:.0f} percent of all speech, leaving "
            f"students {sp:.0f} percent, which reads as a lecture heavy lesson."
        )
    if band == "balanced":
        return (
            f"Talk time splits {tp:.0f} percent teacher to {sp:.0f} percent "
            "students, a balanced pattern for this format."
        )
    return (
        f"Students carry {sp:.0f} percent of the speech against the "
        f"teacher's {tp:.0f} percent, an unusually student led session."
    )


def _participation_sentence(m: dict[str, Any]) -> str:
    q = m["teacher_question_count"]
    r = m["student_response_count"]
    band = m["student_participation_band"]
    if band == "high":
        return (
            f"Of {q} teacher questions, {r} drew student responses, and "
            "students also get real airtime, so participation scores high."
        )
    if band == "moderate":
        return (
            f"The teacher asks {q} questions and students respond {r} times, "
            "moderate participation with room for longer student answers."
        )
    return (
        f"Despite {q} teacher questions there are only {r} student "
        "responses with little airtime, so participation scores low."
    )


def _rhythm_sentence(m: dict[str, Any]) -> str:
    band = m["interaction_density_band"]
    density = m["interaction_density"]
    long_pause = m["long_pause_seconds"]
    if band == "highly interactive":
        lead = (
            f"Question and answer exchanges arrive {density:.1f} times a "
            "minute, a highly interactive rhythm."
        )
    elif band == "active":
        lead = (
            f"At {density:.1f} question and answer exchanges per minute the "
            "dialogue stays active."
        )
    else:
        lead = (
            f"Exchanges are rare at {density:.1f} per minute, so most of the "
            "lesson flows one way."
        )
    if long_pause >= 120:
        lead += (
            f" About {_mins(long_pause)} of long silences suggest written "
            "work or an idle recorder, worth a look on the timeline."
        )
    return lead


def _headcount_sentence(
    m: dict[str, Any], metadata: dict[str, Any]
) -> str | None:
    per_student = m.get("per_student_talk_seconds")
    count = metadata.get("student_count")
    if per_student is None or not count:
        return None
    return (
        f"Across the {count} students on record that averages "
        f"{per_student:.1f} seconds of speech each."
    )


def build_summary(
    metrics: dict[str, Any],
    metadata: dict[str, Any],
    duration_seconds: float | None,
) -> str:
    """Compose the summary paragraph from computed numbers and metadata."""
    sentences = [
        _opening(metadata, duration_seconds),
        _talk_sentence(metrics),
        _participation_sentence(metrics),
        _rhythm_sentence(metrics),
    ]
    headcount = _headcount_sentence(metrics, metadata)
    if headcount:
        sentences.append(headcount)
    return " ".join(sentences)
