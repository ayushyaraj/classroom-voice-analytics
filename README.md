---
title: Classroom Voice Analytics
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Classroom Voice Analytics

I built this to turn a recorded school lesson into a readable picture of who
spoke and how much. It takes an audio recording (plus the optional metadata
JSON and classroom photo the recording app writes), transcribes it, splits
teacher talk from student talk, and reports engagement metrics, a summary, and
an editable transcript. Transcription runs locally by default with no API key,
and an optional Groq cloud backend is available when speed matters more than
running fully offline.

## Live demo

Deploy target is Hugging Face Spaces (Docker). See [docs/DEPLOY.md](docs/DEPLOY.md)
for the full steps. Live link and screenshots go here once deployed.

## Quickstart (local)

Prerequisites: ffmpeg on PATH, Python 3.11, Node 22.

Python 3.13 is not supported because ctranslate2 and faster-whisper do not have
reliable wheels for it. Create the venv explicitly with 3.11.

```
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

If PowerShell blocks Activate.ps1 with an execution policy error, run this once
for the current shell, then activate again:

```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

Run the backend (terminal 1) and the frontend (terminal 2):

```
cd backend
python -m uvicorn app.main:app --port 8000
```

```
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The frontend proxies /api to the backend on 8000.

## Transcription engines

The ASR sits behind a small BaseTranscriber interface, so backends are
swappable.

- Local faster-whisper (CTranslate2), the default. No API key, no quota, runs
  offline after the first model download. int8 on CPU, float16 if CUDA is
  present. This is the honest offline first path, but on CPU it is slow: a
  20 minute recording on the medium model can take 30 minutes or more.
- Groq cloud (optional). Whisper on GPUs behind an OpenAI compatible endpoint,
  many times faster. It needs a GROQ_API_KEY, has a rate limited free tier that
  is not unlimited, and sends audio to a third party. I added it because CPU
  transcription was too slow for a live demo where people will not wait. To use
  it, set GROQ_API_KEY (see .env.example) and pick the Groq option in the model
  selector. Long recordings are sent in a few large chunks and rate limit
  responses are retried with backoff, so the free tier holds for normal use.

Choose Groq for speed, local for zero cost and privacy. On this hardware a
22 minute sample transcribed end to end (preprocess, voice activity detection,
transcription, speaker attribution, metrics) in about 2 minutes 16 seconds on
Groq.

## Language handling

Marathi first, then Hindi, then English, since the sample recordings are from a
government school in Igatpuri, Nashik. The selector defaults to Marathi and
offers Hindi, English, and auto detect. Language detection runs on the first
speech chunks and, if it disagrees with your selection, shows a non blocking
notice rather than overriding you. Code mixing is treated as normal, not
failure. Word error rate rises on code mixed speech, which is expected.

## Engagement metrics

| Metric | Formula | Interpretation |
| --- | --- | --- |
| Teacher Dominance Ratio | teacher talk seconds / total speech seconds | above 0.85 lecture heavy, 0.60 to 0.85 balanced, below 0.60 student led |
| Student Participation Indicator | (student responses / max(teacher questions, 1)) times (student talk / total speech), clamped 0 to 1 | below 0.20 low, 0.20 to 0.50 moderate, above 0.50 high |
| Interaction Density | question and response turn pairs / duration in minutes | below 1 low dialogue, 1 to 3 active, above 3 highly interactive |

## How it works

One ffmpeg pass prepares the audio:

```
ffmpeg -i input -af highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11 -ac 1 -ar 16000 -sample_fmt s16 -y output.wav
```

silero-vad finds speech regions, which are grouped into chunks cut only at
silence boundaries so no word is split. Chunks transcribe in sequence, each
carrying the previous chunk's trailing sentence for continuity, and segments
plus real progress are written to SQLite after every chunk. Memory stays flat
on long files because audio is streamed from disk, never loaded whole.

Speaker attribution is a heuristic, not diarization: two cluster KMeans on
median pitch, energy, duration, word count, and speech rate, with the larger
speech share labelled teacher, then corrected by the multilingual lexicon and
explicit choral response detection. Every label is editable in the UI and all
metrics recompute from corrected labels.

## Metadata ingestion

If a sidecar JSON and image share the audio's base name, they merge into the
session record. The loader is built against the real sample schema
(activityType, boys, girls, totalStudents, duration in milliseconds, teacherId,
timestamp, and a photoMetadata block with address, capturedAt, latitude,
longitude, teacherName) but parses defensively: unknown keys are logged, a
missing sidecar means empty metadata, and malformed JSON records a warning
instead of crashing. GPS and the two timestamps are reconciled against the
recording window and a mismatch surfaces as a small note, because field data is
untrusted input. The classroom photo is shown as context only; no computer
vision runs on it.

## Assumptions and limitations

- Speaker labels are heuristic approximation, not diarization. Accuracy drops on
  overlapping speech and heavy fan noise.
- Code mixing raises word error rate.
- No per student identification; the per student figure is student talk divided
  by the headcount.
- The metadata schema was inferred from the provided samples.
- The Groq path depends on a third party API with a free tier that can rate
  limit or change. Local transcription is the fallback that always works.

## What I would do next

- Real diarization once a self hosted ungated model is viable.
- Per student tracking.
- Multi session and multi school dashboards.
- An Indic fine tuned ASR model added as another BaseTranscriber subclass.
