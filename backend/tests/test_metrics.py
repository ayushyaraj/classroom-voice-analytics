"""Hand-computed assertions for question detection and the three engagement
metrics, over Marathi, Hindi, and English fixture segments."""

from app.pipeline.metrics import (
    analyze,
    id_band,
    interaction_density,
    is_question,
    mark_questions,
    spi_band,
    student_participation_indicator,
    tdr_band,
    teacher_dominance_ratio,
)


def seg(start, end, text, speaker):
    return {"start": start, "end": end, "text": text, "speaker": speaker}


# --- question detection -------------------------------------------------------


def test_marathi_questions():
    assert is_question("he kay aahe")
    assert is_question("kon sangel mala")
    assert is_question("समजलं का मुलांनो")
    assert is_question("किती झाले")


def test_hindi_questions():
    assert is_question("yeh kya hai")
    assert is_question("koi bataye iska matlab")
    assert is_question("समझ आया सबको")


def test_english_questions():
    assert is_question("what is the answer")
    assert is_question("can anyone tell me")
    assert is_question("is that clear")


def test_question_mark_counts():
    assert is_question("ase ka?")


def test_bare_fillers_are_not_questions():
    # 'ho ka' contains the question word 'ka' but is verbal punctuation
    assert not is_question("theek hai")
    assert not is_question("thik hai.")
    assert not is_question("barobar")
    assert not is_question("ho ka")
    assert not is_question("accha")


def test_embedded_question_word_needs_boundary():
    # 'kaystyle' contains 'kay' as a substring but is not the word 'kay'
    assert not is_question("kaystyle nahi chalel")


def test_only_teacher_segments_marked():
    segments = [
        seg(0, 2, "he kay aahe", "TEACHER"),
        seg(3, 4, "kay", "STUDENT"),
    ]
    mark_questions(segments)
    assert segments[0]["is_question"] is True
    assert segments[1]["is_question"] is False


# --- metric formulas -----------------------------------------------------------


def test_tdr_formula_and_bands():
    assert teacher_dominance_ratio(90, 100) == 0.9
    assert teacher_dominance_ratio(0, 0) == 0.0
    assert tdr_band(0.9) == "lecture heavy"
    assert tdr_band(0.7) == "balanced"
    assert tdr_band(0.5) == "student led"


def test_spi_formula_and_bands():
    # 4 responses to 5 questions, students hold 25% of speech time:
    # 0.8 * 0.25 = 0.2
    assert student_participation_indicator(4, 5, 25, 100) == 0.2
    # zero questions uses max(q,1) so it cannot divide by zero
    assert student_participation_indicator(2, 0, 50, 100) == 1.0  # clamped
    assert student_participation_indicator(0, 5, 0, 100) == 0.0
    assert spi_band(0.1) == "low"
    assert spi_band(0.35) == "moderate"
    assert spi_band(0.6) == "high"


def test_interaction_density_formula_and_bands():
    # 30 pairs in 15 minutes = 2 per minute
    assert interaction_density(30, 900) == 2.0
    assert interaction_density(0, 0) == 0.0
    assert id_band(0.5) == "low dialogue"
    assert id_band(2.0) == "active"
    assert id_band(4.0) == "highly interactive"


# --- full analysis --------------------------------------------------------------


def build_fixture():
    """120 s lesson. Hand-computed ground truth:

    teacher talk: 10 + 5 + 5 + 10 = 30 s, student talk: 3 + 2 = 5 s,
    total speech 35 s.
    Questions: 2 (segments at 10 and 60). The reply at 16 lands inside the
    8 s window of the question ending at 15; the reply at 80 misses the
    window of the question ending at 65. So responses 1, pairs 1.
    """
    return [
        seg(0, 10, "aaj aapan ganit shiknar aahot", "TEACHER"),
        seg(10, 15, "he kay aahe sanga", "TEACHER"),
        seg(16, 19, "hoy madam", "STUDENT"),
        seg(60, 65, "doghanchi beriz kiti hote", "TEACHER"),
        seg(80, 82, "vees", "STUDENT"),
        seg(90, 100, "chhan aata pudhcha prashna", "TEACHER"),
    ]


def test_analyze_counts():
    gaps = [2.0, 41.0, 8.0, 4.0, 20.0]  # 1.5-5s short: 2+4=6, >=5s long: 41+8+20=69
    result = analyze(build_fixture(), gaps, 120.0, student_count=20)
    assert result["teacher_talk_seconds"] == 30.0
    assert result["student_talk_seconds"] == 5.0
    assert result["total_speech_seconds"] == 35.0
    assert result["teacher_question_count"] == 2
    assert result["student_response_count"] == 1
    assert result["qa_pair_count"] == 1
    assert result["short_pause_seconds"] == 6.0
    assert result["long_pause_seconds"] == 69.0
    # TDR 30/35
    assert result["teacher_dominance_ratio"] == round(30 / 35, 3)
    # SPI (1/2) * (5/35)
    assert result["student_participation_indicator"] == round(0.5 * 5 / 35, 3)
    # density 1 pair / 2 minutes
    assert result["interaction_density"] == 0.5
    # per student: 5 s / 20 students = 0.25, round-half-even gives 0.2
    assert result["per_student_talk_seconds"] == 0.2


def test_timeline_splits_on_minute_boundary():
    segments = [seg(55, 65, "boundary crossing talk", "TEACHER")]
    result = analyze(segments, [], 120.0, None)
    timeline = result["timeline"]
    assert timeline[0]["teacher_seconds"] == 5.0
    assert timeline[1]["teacher_seconds"] == 5.0
    assert len(timeline) == 2


def test_analyze_recomputes_after_label_flip():
    segments = build_fixture()
    before = analyze(segments, [], 120.0, None)
    segments[2]["speaker"] = "TEACHER"  # flip the 'hoy madam' reply
    after = analyze(segments, [], 120.0, None)
    assert after["teacher_talk_seconds"] == before["teacher_talk_seconds"] + 3.0
    assert after["student_response_count"] == before["student_response_count"] - 1


def test_empty_recording():
    result = analyze([], [], 0.0, None)
    assert result["teacher_dominance_ratio"] == 0.0
    assert result["teacher_question_count"] == 0
    assert result["per_student_talk_seconds"] is None
