"""Local faster-whisper (CTranslate2) backend.

Models download once from the ungated Systran/faster-whisper-* repos on
Hugging Face, no token involved, then run fully offline. int8 on CPU keeps
the medium model around 1.5 GB resident; float16 is used when CUDA exists.
"""

from __future__ import annotations

import logging

import numpy as np

from app.asr.base import AsrSegment, BaseTranscriber

logger = logging.getLogger(__name__)


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class FasterWhisperTranscriber(BaseTranscriber):
    def __init__(self, model_size: str = "medium") -> None:
        # Imported here so the API process can start without the model ever
        # loading; only the worker pays the import and load cost.
        from faster_whisper import WhisperModel

        if _cuda_available():
            device, compute = "cuda", "float16"
        else:
            device, compute = "cpu", "int8"
        logger.info(
            "loading faster-whisper %s on %s (%s)", model_size, device, compute
        )
        self._model = WhisperModel(model_size, device=device, compute_type=compute)
        self._compute_type = compute
        self._model_size = model_size

    @property
    def compute_type(self) -> str:
        return self._compute_type

    def transcribe_chunk(
        self,
        audio: np.ndarray,
        language: str | None,
        initial_prompt: str | None = None,
    ) -> list[AsrSegment]:
        # beam_size 5 is the faster-whisper default quality setting;
        # condition_on_previous_text stays False because hallucination loops
        # on noisy classroom audio are worse than lost cross-segment context,
        # which initial_prompt already provides at chunk boundaries.
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            initial_prompt=initial_prompt,
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=False,  # chunking already ran silero-vad
        )
        return [
            AsrSegment(
                start=s.start,
                end=s.end,
                text=s.text.strip(),
                avg_logprob=s.avg_logprob,
            )
            for s in segments
            if s.text.strip()
        ]

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        _segments, info = self._model.transcribe(audio, language=None)
        return info.language, float(info.language_probability)
