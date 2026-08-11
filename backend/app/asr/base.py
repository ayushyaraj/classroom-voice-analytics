"""Transcriber interface.

The only shipped backend is local faster-whisper, which needs no key, no
login, and no network after the first model download. An Indic fine-tuned
model can be added later as one more subclass without touching the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class AsrSegment:
    """One transcribed span, seconds relative to the audio passed in."""

    start: float
    end: float
    text: str
    avg_logprob: float


class BaseTranscriber(ABC):
    """A transcriber receives one chunk of 16 kHz mono float32 audio at a
    time; the pipeline owns chunking, context carrying, and persistence."""

    @abstractmethod
    def transcribe_chunk(
        self,
        audio: np.ndarray,
        language: str | None,
        initial_prompt: str | None = None,
    ) -> list[AsrSegment]:
        """Transcribe one chunk.

        audio: float32 mono at 16 kHz.
        language: ISO code, or None to autodetect.
        initial_prompt: trailing sentence of the previous chunk, carried for
            continuity across chunk boundaries.
        """

    @abstractmethod
    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        """Return (language_code, probability) for one chunk of audio."""

    @property
    @abstractmethod
    def compute_type(self) -> str:
        """Which compute path actually loaded, e.g. int8 or float16."""
