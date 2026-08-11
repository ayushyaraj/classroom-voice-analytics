"""Sidecar JSON metadata loader.

Built against the real sample sidecar written by the Android recording app
(com.example.mneapplication). Its actual schema, verified on disk:

    activityType, boys, girls, totalStudents, duration (milliseconds),
    teacherId, timestamp, recordingFilePath,
    photoMetadata { address, capturedAt, latitude, longitude, photoPath,
                    teacherName }

Everything is still parsed defensively as an untyped dict because this is
field data from an app we do not control. Unknown keys are logged so a human
can extend ALIASES. Missing sidecar means empty metadata; malformed sidecar
means a warning, never a crash.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SessionMetadata:
    school_name: str | None = None
    school_id: str | None = None
    village: str | None = None
    district: str | None = None
    state: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    recorded_at: str | None = None
    photo_captured_at: str | None = None
    teacher_name: str | None = None
    teacher_id: str | None = None
    class_or_grade: str | None = None
    subject: str | None = None
    activity_type: str | None = None
    device_id: str | None = None
    duration_seconds: float | None = None
    observer_name: str | None = None
    student_count: int | None = None
    boys: int | None = None
    girls: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Maps a lowercased source key to a SessionMetadata field. Keys observed in
# the real sample sit alongside plausible variants from other form-builder
# style apps, since the schema was inferred from a single sample.
ALIASES: dict[str, str] = {
    # real sample keys
    "activitytype": "activity_type",
    "boys": "boys",
    "girls": "girls",
    "totalstudents": "student_count",
    "teacherid": "teacher_id",
    "teachername": "teacher_name",
    "timestamp": "recorded_at",
    "duration": "duration_seconds",
    "address": "address",
    "capturedat": "photo_captured_at",
    "latitude": "latitude",
    "longitude": "longitude",
    # plausible variants
    "school": "school_name",
    "schoolname": "school_name",
    "school_name": "school_name",
    "centre": "school_name",
    "center": "school_name",
    "schoolid": "school_id",
    "school_id": "school_id",
    "udise": "school_id",
    "village": "village",
    "district": "district",
    "state": "state",
    "lat": "latitude",
    "lng": "longitude",
    "long": "longitude",
    "lon": "longitude",
    "date": "recorded_at",
    "recordedat": "recorded_at",
    "recorded_at": "recorded_at",
    "author": "observer_name",
    "recordedby": "observer_name",
    "observer": "observer_name",
    "observername": "observer_name",
    "std": "class_or_grade",
    "grade": "class_or_grade",
    "class": "class_or_grade",
    "classname": "class_or_grade",
    "subj": "subject",
    "subject": "subject",
    "deviceid": "device_id",
    "device_id": "device_id",
    "studentcount": "student_count",
    "student_count": "student_count",
    "students": "student_count",
}

# Device-local file paths from the recording phone. Known, deliberately not
# mapped: they point into another device's storage and are useless here.
IGNORED_KEYS = {"recordingfilepath", "photopath", "photometadata"}

INT_FIELDS = {"student_count", "boys", "girls"}
FLOAT_FIELDS = {"latitude", "longitude", "duration_seconds"}

# Recording filenames look like OD11163_2025-12-23-121239: teacher id, then
# the recording start time.
FILENAME_TS = re.compile(r"_(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})$")

# The sidecar timestamps carry no timezone; both come from the same phone so
# they compare against each other directly.
SIDECAR_TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# Rough bounding box of India. Field GPS outside it is worth a warning, since
# these recordings all come from Maharashtra schools.
INDIA_LAT = (6.0, 38.0)
INDIA_LON = (68.0, 98.0)


def _coerce(field_name: str, value: Any, warnings: list[str]) -> Any:
    """Cast a raw JSON value to the field's type, warning instead of raising."""
    if value is None:
        return None
    try:
        if field_name in INT_FIELDS:
            return int(value)
        if field_name in FLOAT_FIELDS:
            result = float(value)
            if field_name == "duration_seconds" and result > 36000:
                # The real app writes milliseconds. Ten hours of classroom
                # audio is implausible, so anything above that is ms.
                result = result / 1000.0
            return result
        return str(value).strip() or None
    except (TypeError, ValueError):
        warnings.append(f"could not parse {field_name}={value!r}, ignored")
        return None


def _flatten(raw: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """One level of nesting is enough for the observed schema, but recursing
    costs nothing and survives a deeper future schema."""
    flat: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            flat[key] = value  # keep the parent key so it can be ignored
            flat.update(_flatten(value, prefix=f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}" if prefix else key] = value
    return flat


def _split_address(meta: SessionMetadata) -> None:
    """Best-effort locality extraction from a comma separated address string,
    e.g. 'Shop No 1 Igatpuri Giranare, Igatpuri, Maharashtra, India'.
    Only fills fields that are still empty; a real village/district/state key
    always wins over this heuristic."""
    if not meta.address:
        return
    parts = [p.strip() for p in meta.address.split(",") if p.strip()]
    # last part is the country, second last the state, third last the town.
    if len(parts) >= 3 and meta.state is None:
        meta.state = parts[-2]
    if len(parts) >= 3 and meta.village is None:
        meta.village = parts[-3]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), SIDECAR_TS_FORMAT)
    except ValueError:
        return None


def _reconcile(
    meta: SessionMetadata, base_name: str | None, warnings: list[str]
) -> None:
    """Cross-check the sidecar's claims against each other and against the
    recording filename. Field data is untrusted input; disagreements get a
    warning the UI can surface, never an error."""
    if (
        meta.student_count is not None
        and meta.boys is not None
        and meta.girls is not None
        and meta.boys + meta.girls != meta.student_count
    ):
        warnings.append(
            f"boys ({meta.boys}) + girls ({meta.girls}) does not equal "
            f"totalStudents ({meta.student_count})"
        )

    if meta.latitude is not None and meta.longitude is not None:
        if not (
            INDIA_LAT[0] <= meta.latitude <= INDIA_LAT[1]
            and INDIA_LON[0] <= meta.longitude <= INDIA_LON[1]
        ):
            warnings.append(
                f"GPS ({meta.latitude}, {meta.longitude}) is outside India, "
                "photo location overlay may not match"
            )

    start: datetime | None = None
    if base_name:
        match = FILENAME_TS.search(base_name)
        if match:
            y, mo, d, h, mi, s = (int(g) for g in match.groups())
            try:
                start = datetime(y, mo, d, h, mi, s)
            except ValueError:
                start = None

    captured = _parse_ts(meta.photo_captured_at)
    recorded = _parse_ts(meta.recorded_at)
    duration = timedelta(seconds=meta.duration_seconds or 0)
    # 15 minutes of slack absorbs clock drift and the observer photographing
    # the room before pressing record.
    slack = timedelta(minutes=15)

    if start and captured and not (
        start - slack <= captured <= start + duration + slack
    ):
        warnings.append(
            f"photo capturedAt {meta.photo_captured_at} falls outside the "
            f"recording window starting {start}"
        )
    if start and recorded and not (
        start - slack <= recorded <= start + duration + slack
    ):
        warnings.append(
            f"sidecar timestamp {meta.recorded_at} falls outside the "
            f"recording window starting {start}"
        )


def parse_metadata(
    raw: Any, base_name: str | None = None
) -> tuple[SessionMetadata, list[str], list[str]]:
    """Normalize an untyped sidecar dict.

    Returns (metadata, unmapped_keys, warnings). raw may be anything JSON
    can produce; only a dict yields fields, everything else yields empty
    metadata plus a warning.
    """
    meta = SessionMetadata()
    unmapped: list[str] = []
    warnings: list[str] = []

    if not isinstance(raw, dict):
        warnings.append(f"sidecar JSON root is {type(raw).__name__}, expected object")
        return meta, unmapped, warnings

    flat = _flatten(raw)
    for key, value in flat.items():
        # nested keys arrive both as 'photoMetadata.latitude' and 'latitude';
        # match the alias on the leaf name.
        leaf = key.rsplit(".", 1)[-1].lower().replace(" ", "").replace("-", "")
        if leaf in IGNORED_KEYS:
            continue
        target = ALIASES.get(leaf)
        if target is None:
            if "." not in key:  # avoid double-reporting nested leaves
                unmapped.append(key)
                logger.info("sidecar key not in alias map: %s", key)
            continue
        if getattr(meta, target) is None:
            setattr(meta, target, _coerce(target, value, warnings))

    _split_address(meta)
    _reconcile(meta, base_name, warnings)
    return meta, unmapped, warnings


def load_sidecar(
    json_path: Path, base_name: str | None = None
) -> tuple[SessionMetadata, list[str], list[str]]:
    """Load and normalize a sidecar file. Missing file: empty metadata, no
    warning (a bare audio upload is normal). Malformed file: empty metadata
    plus a warning."""
    if not json_path.exists():
        return SessionMetadata(), [], []
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return (
            SessionMetadata(),
            [],
            [f"sidecar JSON could not be parsed: {exc}"],
        )
    return parse_metadata(raw, base_name=base_name or json_path.stem)
