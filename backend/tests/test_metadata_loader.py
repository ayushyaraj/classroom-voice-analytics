"""Tests for the sidecar metadata loader against the real observed schema,
alias variants, and deliberately broken input."""

import json
from pathlib import Path

from app.metadata.loader import SessionMetadata, load_sidecar, parse_metadata

# Mirrors the real sample sidecar, values changed but shape identical.
REAL_SHAPE = {
    "activityType": "Trumpet",
    "boys": 15,
    "girls": 7,
    "duration": 4062420,
    "photoMetadata": {
        "address": "Shop No 1 Igatpuri Giranare, Igatpuri, Maharashtra, India",
        "capturedAt": "2025-12-23 12:13:06",
        "latitude": 19.6962197,
        "longitude": 73.5798404,
        "photoPath": "/storage/emulated/0/x.jpg",
        "teacherName": "Santana",
    },
    "recordingFilePath": "/storage/emulated/0/x.mp3",
    "teacherId": "OD11163",
    "timestamp": "2025-12-23 13:21:25",
    "totalStudents": 22,
}


def test_real_schema_maps_fully():
    meta, unmapped, warnings = parse_metadata(
        REAL_SHAPE, base_name="OD11163_2025-12-23-121239"
    )
    assert meta.activity_type == "Trumpet"
    assert meta.boys == 15
    assert meta.girls == 7
    assert meta.student_count == 22
    assert meta.teacher_id == "OD11163"
    assert meta.teacher_name == "Santana"
    assert meta.latitude == 19.6962197
    assert meta.longitude == 73.5798404
    assert meta.recorded_at == "2025-12-23 13:21:25"
    assert meta.photo_captured_at == "2025-12-23 12:13:06"
    # duration arrives in milliseconds and must come out in seconds
    assert meta.duration_seconds == 4062.42
    # every real key maps or is deliberately ignored
    assert unmapped == []
    # 15 + 7 == 22 and both timestamps sit inside the recording window
    assert warnings == []


def test_address_locality_heuristic():
    meta, _, _ = parse_metadata(REAL_SHAPE)
    assert meta.state == "Maharashtra"
    assert meta.village == "Igatpuri"


def test_alias_variants():
    raw = {
        "schoolName": "ZP School Igatpuri",
        "std": "4",
        "subj": "Maths",
        "lat": "19.7",
        "lng": "73.5",
        "recordedBy": "Observer A",
        "students": "24",
    }
    meta, unmapped, warnings = parse_metadata(raw)
    assert meta.school_name == "ZP School Igatpuri"
    assert meta.class_or_grade == "4"
    assert meta.subject == "Maths"
    assert meta.latitude == 19.7
    assert meta.longitude == 73.5
    assert meta.observer_name == "Observer A"
    assert meta.student_count == 24
    assert unmapped == []
    assert warnings == []


def test_unknown_keys_are_reported_not_fatal():
    meta, unmapped, _ = parse_metadata({"frobnicator": 1, "teacherName": "X"})
    assert meta.teacher_name == "X"
    assert unmapped == ["frobnicator"]


def test_headcount_mismatch_warns():
    raw = dict(REAL_SHAPE, boys=10)
    _, _, warnings = parse_metadata(raw, base_name="OD11163_2025-12-23-121239")
    assert any("totalStudents" in w for w in warnings)


def test_photo_timestamp_outside_window_warns():
    raw = json.loads(json.dumps(REAL_SHAPE))
    raw["photoMetadata"]["capturedAt"] = "2025-12-25 09:00:00"
    _, _, warnings = parse_metadata(raw, base_name="OD11163_2025-12-23-121239")
    assert any("capturedAt" in w for w in warnings)


def test_gps_outside_india_warns():
    raw = json.loads(json.dumps(REAL_SHAPE))
    raw["photoMetadata"]["latitude"] = 48.85
    raw["photoMetadata"]["longitude"] = 2.35
    _, _, warnings = parse_metadata(raw)
    assert any("GPS" in w for w in warnings)


def test_unparseable_numbers_warn_not_crash():
    meta, _, warnings = parse_metadata({"totalStudents": "twenty", "boys": []})
    assert meta.student_count is None
    assert meta.boys is None
    assert len(warnings) == 2


def test_non_dict_root():
    meta, unmapped, warnings = parse_metadata([1, 2, 3])
    assert meta == SessionMetadata()
    assert warnings and "expected object" in warnings[0]


def test_missing_sidecar_is_silent(tmp_path: Path):
    meta, unmapped, warnings = load_sidecar(tmp_path / "nope.json")
    assert meta == SessionMetadata()
    assert unmapped == []
    assert warnings == []


def test_malformed_sidecar_warns(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"teacherName": "X", oops', encoding="utf-8")
    meta, _, warnings = load_sidecar(bad)
    assert meta == SessionMetadata()
    assert warnings and "could not be parsed" in warnings[0]
