"""Groq cloud transcription backend.

Optional fast path. Groq runs Whisper on GPUs behind an OpenAI-compatible
endpoint, so a chunk transcribes in about a second instead of tens of seconds
on local CPU. This backend plugs into the same BaseTranscriber interface the
worker already drives, so the chunking, context carrying, and persistence are
unchanged; only the per chunk call is remote.

Tradeoffs, stated honestly because the default design deliberately avoided a
hosted API: this needs a GROQ_API_KEY, it has a rate limited free tier (not
unlimited), and it sends classroom audio to a third party. The key is read
only from the environment and never written anywhere.
"""

from __future__ import annotations

import io
import logging
import os
import time

import httpx
import numpy as np
import soundfile as sf

from app.asr.base import AsrSegment, BaseTranscriber
from app.config import (
    GROQ_ENDPOINT,
    GROQ_MAX_RETRIES,
    GROQ_MODEL,
    TARGET_SAMPLE_RATE,
)
from app.pipeline.preprocess import AudioError

logger = logging.getLogger(__name__)


class GroqCloudTranscriber(BaseTranscriber):
    def __init__(self, model: str | None = None) -> None:
        self._api_key = os.environ.get("GROQ_API_KEY")
        if not self._api_key:
            # AudioError surfaces as a clean user message and a failed job row,
            # not a stack trace.
            raise AudioError(
                "The fast cloud engine needs a Groq API key. Set GROQ_API_KEY "
                "in the environment, or pick a local model size instead."
            )
        self._model = model or GROQ_MODEL
        # A single chunk upload is small; 120 s is a generous ceiling that still
        # fails fast if the network hangs.
        self._client = httpx.Client(timeout=120)
        logger.info("using Groq backend, model %s", self._model)

    @property
    def compute_type(self) -> str:
        return f"groq:{self._model}"

    def _encode(self, audio: np.ndarray) -> bytes:
        # Encode the 16 kHz mono float32 chunk to a 16 bit wav in memory.
        buffer = io.BytesIO()
        sf.write(buffer, audio, TARGET_SAMPLE_RATE, format="WAV", subtype="PCM_16")
        return buffer.getvalue()

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        """Seconds to wait before retrying a rate-limited request. Prefer the
        server's Retry-After header; otherwise back off exponentially."""
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(float(header), 30.0)
            except ValueError:
                pass
        # 2, 4, 8, ... capped so a job never stalls for minutes on one chunk
        return min(2.0 * (2 ** attempt), 30.0)

    def _post(
        self, audio: np.ndarray, language: str | None, prompt: str | None
    ) -> dict:
        wav = self._encode(audio)
        data = {
            "model": self._model,
            "response_format": "verbose_json",  # gives per segment timestamps
            "temperature": "0",
        }
        if language and language != "auto":
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        last_status = None
        for attempt in range(GROQ_MAX_RETRIES):
            try:
                response = self._client.post(
                    GROQ_ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files={"file": ("chunk.wav", io.BytesIO(wav), "audio/wav")},
                )
            except httpx.HTTPError as exc:
                raise AudioError(
                    "Could not reach the Groq service. Check the internet "
                    "connection and retry, or use a local model size."
                ) from exc

            if response.status_code == 401:
                raise AudioError("The Groq API key was rejected. Check GROQ_API_KEY.")
            if response.status_code == 413:
                raise AudioError("A chunk was too large for Groq to accept.")
            # rate limited or transiently unavailable: wait and retry
            if response.status_code in (429, 503):
                last_status = response.status_code
                wait = self._retry_after(response, attempt)
                logger.info(
                    "groq %s, waiting %.1fs (attempt %d/%d)",
                    response.status_code, wait, attempt + 1, GROQ_MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            if response.status_code >= 400:
                logger.warning(
                    "groq error %s: %s", response.status_code, response.text[:300]
                )
                raise AudioError(f"Groq returned an error ({response.status_code}).")
            return response.json()

        raise AudioError(
            "Groq stayed rate limited after several retries. The free tier "
            "resets after a short wait, or switch to a local model size. "
            f"(last status {last_status})"
        )

    def transcribe_chunk(
        self,
        audio: np.ndarray,
        language: str | None,
        initial_prompt: str | None = None,
    ) -> list[AsrSegment]:
        resp = self._post(audio, language, initial_prompt)
        out: list[AsrSegment] = []
        for s in resp.get("segments", []):
            text = (s.get("text") or "").strip()
            if text:
                out.append(
                    AsrSegment(
                        start=float(s.get("start", 0.0)),
                        end=float(s.get("end", 0.0)),
                        text=text,
                        avg_logprob=float(s.get("avg_logprob", 0.0)),
                    )
                )
        return out

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        resp = self._post(audio, None, None)
        # verbose_json returns a language name or code; Groq does not give a
        # probability, so report full confidence.
        return resp.get("language", "unknown"), 1.0
