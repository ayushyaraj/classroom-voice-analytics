"""Voice activity detection and chunk planning.

silero-vad (torch.hub, MIT licensed, no login) scans the preprocessed wav in
streamed blocks so a two hour file never sits in RAM. Speech regions are then
grouped into 30 to 60 second chunks whose cuts always land on a VAD silence
boundary, so no word is split across a transcription call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
import torch

from app.config import (
    CHUNK_MAX_SECONDS,
    CHUNK_MIN_SECONDS,
    TARGET_SAMPLE_RATE,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_SPEECH_PAD_MS,
    VAD_THRESHOLD,
)

logger = logging.getLogger(__name__)

# silero-vad v5 requires exactly 512-sample windows at 16 kHz.
VAD_WINDOW = 512
# Read the wav in ~16 s blocks: big enough to amortize IO, small enough to
# keep peak memory per block around 1 MB.
BLOCK_WINDOWS = 500

_model = None
_vad_iterator_cls = None


def _load_vad():
    """Load silero-vad once per process via torch.hub."""
    global _model, _vad_iterator_cls
    if _model is None:
        _model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            onnx=False,
        )
        # utils: (get_speech_timestamps, save_audio, read_audio,
        #         VADIterator, collect_chunks)
        _vad_iterator_cls = utils[3]
    return _model, _vad_iterator_cls


@dataclass
class Region:
    """One continuous speech region, seconds from file start."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Chunk:
    """A transcription unit covering one or more speech regions."""

    start: float
    end: float
    regions: list[Region] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def detect_speech_regions(
    wav_path: Path,
    progress_cb: Callable[[float], None] | None = None,
) -> list[Region]:
    """Run streamed VAD over the wav and return speech regions in seconds.

    progress_cb receives a 0..1 fraction of file scanned, so the UI can show
    real VAD progress on a long file.
    """
    model, vad_iterator_cls = _load_vad()
    vad = vad_iterator_cls(
        model,
        threshold=VAD_THRESHOLD,
        sampling_rate=TARGET_SAMPLE_RATE,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_SPEECH_PAD_MS,
    )

    regions: list[Region] = []
    open_start: float | None = None

    with sf.SoundFile(wav_path) as f:
        if f.samplerate != TARGET_SAMPLE_RATE:
            raise ValueError(
                f"expected {TARGET_SAMPLE_RATE} Hz wav, got {f.samplerate}"
            )
        total_frames = f.frames or 1
        frames_read = 0
        while True:
            block = f.read(VAD_WINDOW * BLOCK_WINDOWS, dtype="float32")
            if len(block) == 0:
                break
            frames_read += len(block)
            if block.ndim > 1:
                block = block[:, 0]
            for i in range(0, len(block), VAD_WINDOW):
                window = block[i : i + VAD_WINDOW]
                if len(window) < VAD_WINDOW:
                    window = np.pad(window, (0, VAD_WINDOW - len(window)))
                event = vad(torch.from_numpy(window))
                if event is None:
                    continue
                if "start" in event:
                    open_start = event["start"] / TARGET_SAMPLE_RATE
                elif "end" in event and open_start is not None:
                    regions.append(
                        Region(open_start, event["end"] / TARGET_SAMPLE_RATE)
                    )
                    open_start = None
            if progress_cb:
                progress_cb(min(frames_read / total_frames, 1.0))
        # speech still open at EOF closes at file end
        if open_start is not None:
            regions.append(Region(open_start, frames_read / TARGET_SAMPLE_RATE))

    vad.reset_states()
    min_speech = VAD_MIN_SPEECH_MS / 1000.0
    kept = [r for r in regions if r.duration >= min_speech]
    logger.info(
        "VAD: %d regions kept (%d dropped as blips), %.1f s speech",
        len(kept),
        len(regions) - len(kept),
        sum(r.duration for r in kept),
    )
    return kept


def plan_chunks(regions: list[Region]) -> list[Chunk]:
    """Group speech regions into 30 to 60 second chunks.

    Every boundary between regions is a VAD silence, so closing a chunk at a
    region edge never splits a word. A single continuous region longer than
    CHUNK_MAX_SECONDS is split at the cap.
    TODO: split oversized continuous regions at their quietest frame instead
    of a hard cap; with 300 ms minimum silence this almost never triggers on
    classroom audio, but a hard cap can clip a word when it does.
    """
    chunks: list[Chunk] = []
    current: Chunk | None = None

    def close(chunk: Chunk | None) -> None:
        if chunk is not None and chunk.regions:
            chunks.append(chunk)

    for region in regions:
        # split a pathological continuous region at the cap
        while region.duration > CHUNK_MAX_SECONDS:
            head = Region(region.start, region.start + CHUNK_MAX_SECONDS)
            close(current)
            current = None
            chunks.append(Chunk(head.start, head.end, [head]))
            region = Region(head.end, region.end)

        if current is None:
            current = Chunk(region.start, region.end, [region])
        elif region.end - current.start > CHUNK_MAX_SECONDS:
            close(current)
            current = Chunk(region.start, region.end, [region])
        else:
            current.regions.append(region)
            current.end = region.end
            if current.duration >= CHUNK_MIN_SECONDS:
                close(current)
                current = None
    close(current)
    return chunks


def silence_gaps(regions: list[Region], total_seconds: float) -> list[float]:
    """Durations of the silences between speech regions, including lead-in
    and tail. Used by the analysis stage to split short pauses from long
    dead air."""
    gaps: list[float] = []
    prev_end = 0.0
    for region in regions:
        gap = region.start - prev_end
        if gap > 0:
            gaps.append(gap)
        prev_end = region.end
    tail = total_seconds - prev_end
    if tail > 0:
        gaps.append(tail)
    return gaps
