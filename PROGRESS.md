# PROGRESS

Working file for session continuity. If a session restarts, read this first and
continue from the first unchecked item. Do not restart completed work.

## Verified facts (do not re-derive)

- Sample JSON schema (real, from input-samples\AUDIO SAMPLE 002\OD11163_2025-12-23-121239.json):
  activityType, boys, girls, totalStudents, duration (milliseconds),
  teacherId, timestamp (recording end), recordingFilePath,
  photoMetadata { address, capturedAt, latitude, longitude, photoPath, teacherName }.
  No school_name, district, class_or_grade, or subject keys exist.
- ffprobe on the sample: AAC in an MP4/M4A container with a .mp3 extension
  (format_name mov,mp4,m4a,3gp,3g2,mj2), mono, 44100 Hz, 4062.19 s, 65.7 MB.
- input-samples has 5 triplets in subfolders named "AUDIO SAMPLE 001".."005".
  The reference sample is AUDIO SAMPLE 002 (OD11163_2025-12-23-121239).
- This process has a stale environment: ffmpeg and HF_TOKEN are set at user level
  in the registry but not in the inherited process env. Every PowerShell command
  that needs them must refresh: 
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
  ffmpeg lives at C:\Users\ayush\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe.
  HF_TOKEN loads via [Environment]::GetEnvironmentVariable('HF_TOKEN','User'),
  never print or write its value.
- Python: use py -3.11 (3.11.9). Never 3.13.

## Approved decisions

- Pinned dependency list approved by the user (see backend/requirements.txt).
- torch is used only for silero-vad via torch.hub, per the brief.
- Long commands (pip install, full transcription) run in the background logging
  to logs\, never blocking foreground.
- Push to GitHub after backend tests pass, after frontend, and a final push.

## Checklist

- [x] Read sample JSON, ffprobe the mp3, report findings
- [x] .gitignore, .env.example, PROGRESS.md
- [x] git init, branch main, origin, first commit
- [x] venv (py -3.11), verify 3.11.9, background pip install to logs\install.log
- [x] backend/app/config/__init__.py (config.py would collide with the
      config/ package holding lexicons.py, noted for README) and lexicons.py
- [x] backend/app/db.py
- [x] backend/app/metadata/loader.py plus tests (25 tests pass)
- [x] backend/app/pipeline/preprocess.py
- [x] backend/app/pipeline/chunker.py
- [x] backend/app/asr/base.py and faster_whisper_backend.py
- [x] backend/app/pipeline/speakers.py
- [x] backend/app/pipeline/metrics.py plus tests
- [x] backend/app/pipeline/summary.py
- [x] backend/app/routes/jobs.py, worker.py, ingest.py, main.py
- [x] 60 s trimmed clip at samples/classroom_sample_60s.mp3, command:
      ffmpeg -ss 600 -t 60 -i "input-samples\AUDIO SAMPLE 002\OD11163_2025-12-23-121239.mp3" -ac 1 -b:a 64k samples\classroom_sample_60s.mp3
- [x] smoke test: 60 s clip end to end with tiny model passed. Whole
      pipeline runs: preprocess, VAD, chunk, transcribe, speaker attribution,
      metrics, summary. Metadata merged from real sidecar (village Igatpuri,
      teacher Santana, 22 students). Language notice fired correctly (selected
      mr, detected hi, did not override).
- [x] run pytest (25 pass), fixes applied: added torchaudio==2.6.0 (silero
      hub imports it), pinned silero-vad to v5.1.2, summary handles zero
      questions and 1-minute singular, added /api/jobs/demo/id route.
- [x] pushed backend, opened PR #1 (base main = scaffold, head branch = build)
- [x] frontend (React + Vite, plain CSS modules): upload, processing, results
      with metric cards, activity strip, virtualized editable transcript
- [x] 60 s trimmed clip in samples/, trim command documented in README
- [x] Groq cloud backend added behind BaseTranscriber (speed over local CPU).
      Large-chunk batching + 429 retry to survive the free tier. Verified: real
      22 min file done in ~2 min 16 s on Groq (vs 30-45 min local medium).
- [x] Dockerfile (two stage, HF Spaces port 7860), README with real numbers,
      docs/DEPLOY.md with HF Spaces + Vercel/Render breakdown
- [x] merged build branch into main, pushed main (repo complete)
- [ ] full 67 min local verification run for local-path wall clock and peak RSS
      (Groq path is the shipped fast path; local numbers still pending)
- [ ] pre-computed demo result baked for deploy (demo_job_id is local/ephemeral
      right now; the "View sample result" link only shows when a marker exists)
- [ ] docs/architecture.md
- [ ] actually deploy to HF Spaces and paste the live link into the README

## Deployment quick reference

- Dockerfile at repo root builds frontend + serves it from FastAPI on 7860.
- HF Spaces: push repo to the Space remote, set GROQ_API_KEY as a Space secret.
- Groq key lives only in .env locally and in the host secret store, never in git.
- Full steps: docs/DEPLOY.md.

## In progress

Deployment. Everything else built and verified locally.
