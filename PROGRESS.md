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
- [ ] git init, branch main, origin, first commit
- [ ] venv (py -3.11), verify 3.11.9, background pip install to logs\install.log
- [ ] backend/app/config.py and backend/app/config/lexicons.py
- [ ] backend/app/db.py
- [ ] backend/app/metadata/loader.py plus tests
- [ ] backend/app/pipeline/preprocess.py
- [ ] backend/app/pipeline/chunker.py
- [ ] backend/app/asr/base.py and faster_whisper_backend.py
- [ ] backend/app/pipeline/speakers.py
- [ ] backend/app/pipeline/metrics.py plus tests
- [ ] backend/app/pipeline/summary.py
- [ ] backend/app/routes/jobs.py, worker.py, main.py
- [ ] run pytest, fix, push backend
- [ ] full 67 min verification run in background, record wall clock and peak RSS
- [ ] frontend (React + Vite, plain CSS modules)
- [ ] 60 s trimmed clip in samples/, document trim command
- [ ] Dockerfile, docs/architecture.md, README with real numbers
- [ ] pre-computed demo result for the trimmed sample
- [ ] final push, print manual HF Spaces deploy steps

## In progress

git init and first commit.
