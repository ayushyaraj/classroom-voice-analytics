# Deployment

## Why not Vercel or Netlify alone

Vercel and Netlify host static frontends and short lived serverless functions.
This app is not that. The backend is a long running FastAPI process with a
background worker, a SQLite job queue, ffmpeg subprocesses, and (on the local
path) a 1.5 GB speech model. Serverless functions time out in seconds, cannot
run ffmpeg easily, and have no persistent process or disk. So the Python
backend cannot run on Vercel or Netlify.

Two workable shapes:

- Recommended: one container on Hugging Face Spaces (Docker). The frontend is
  built and served by FastAPI, so the whole app is one live link on one port.
  Free tier, and because Groq does the heavy transcription, the free CPU box
  stays fast.
- Split: frontend on Vercel or Netlify, backend on a container host (Render,
  Railway, Fly). More moving parts and CORS to configure. Use this only if you
  specifically want the frontend on Vercel.

Both use the same Dockerfile at the repo root.

## Option A: Hugging Face Spaces (recommended, one link)

1. Create the Space. Go to https://huggingface.co/new-space. Name it, set SDK to
   Docker, visibility public. This gives you a git repo at
   https://huggingface.co/spaces/<user>/<space>.

2. The Space reads README.md front matter. The repo README already has the
   block it needs:

   ```
   ---
   title: Classroom Voice Analytics
   colorFrom: gray
   colorTo: blue
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```

3. Add the Space as a second remote and push. From the project root:

   ```
   git remote add space https://huggingface.co/spaces/<user>/<space>
   git push space main
   ```

   When git asks for a password, use your Hugging Face access token from
   https://huggingface.co/settings/tokens (a write token). Do not paste the
   token into any file.

4. Set the Groq key as a Space secret, not in the repo. In the Space, open
   Settings, then Variables and secrets, then add a secret named GROQ_API_KEY
   with your key. The app reads it from the environment at runtime.

5. The Space builds the Dockerfile and starts on port 7860. First build takes a
   few minutes. When it finishes you get the live link:
   https://<user>-<space>.hf.space

Notes:
- The local faster-whisper models are not baked into the image, to keep it
  small. On the deployed box, use the Groq engine (fast). If you select a local
  model there, the first run downloads it, which is slow on free CPU.
- Space storage is ephemeral. Uploaded files and the job database reset when the
  Space restarts. That is fine for a demo; add a persistent volume if you need
  history to survive restarts.

## Option B: Vercel frontend plus Render backend

Backend on Render:

1. Push this repo to GitHub (already done).
2. On https://render.com create a new Web Service from the repo, environment
   Docker. Render uses the root Dockerfile.
3. Set the start command port to match: Render provides $PORT, so either change
   the Dockerfile CMD to use $PORT or set app_port. Simplest is to add an env
   var and run uvicorn on it. For Render, set the Docker CMD port to 10000 or
   read $PORT.
4. Add GROQ_API_KEY as an environment variable in the Render dashboard.
5. Render gives you a backend URL like https://your-api.onrender.com.

Frontend on Vercel:

1. The frontend calls /api/... relative paths. For a split deploy, point those
   at the backend URL. Set an env var VITE_API_BASE to the Render URL and change
   frontend/src/api.js to prefix requests with it, or add a Vercel rewrite so
   /api/* proxies to the Render backend.
2. On https://vercel.com import the repo, set the root directory to frontend,
   framework Vite. Build command npm run build, output dist.
3. Vercel gives you the frontend URL.
4. Enable CORS on the backend for the Vercel domain (the app already allows
   localhost:5173 in dev; add the Vercel origin for production).

This works but is more setup than Option A. For a single live link with the
least effort, use Hugging Face Spaces.

## Rotating the Groq key

If a key was ever written to a tracked file or shared, revoke it and make a new
one:

1. Go to https://console.groq.com, open API Keys.
2. Delete the old key.
3. Create a new key.
4. Put it in the local .env (GROQ_API_KEY=...) for local runs, and in the Space
   or Render secret for the deployed app. Never commit it.
