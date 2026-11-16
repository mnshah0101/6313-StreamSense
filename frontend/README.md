# StreamSense review UI

Review tool for StreamSense: upload match footage, watch the analysis fill the timeline,
and review alerts and model output. Styling: dark, dense, one red accent
(Druk + Siro fonts when the licensed files are present).

## Run

```sh
npm install
npm run dev        # http://127.0.0.1:5173
npm run build      # typecheck + production build into dist/
```

Node 24 (see the sibling repo's `.node-version`).

## Running against the API

The UI reads everything from the StreamSense API (`../backend`); there are no fixtures
and no demo data. A fresh API starts empty: the catalog shows a call to action until the first
upload, the alerts sidebar says there are no alerts, and Model Performance says there are no
evaluated runs until one is imported (`POST /runs/import`).

```sh
# 1. API, from ../backend (dummy backend, local media under var/)
uv run uvicorn app.main:app --port 8000

# 2. UI
cp .env.example .env.local      # VITE_API_URL=/api (dev proxy) or http://127.0.0.1:8000
npm run dev                     # http://127.0.0.1:5173 (allowed by the API's CORS defaults)
```

`VITE_API_URL` is baked in at build time, so set it in the deploy environment too. Use the
same-origin `/api` proxy: sign-in is an HttpOnly session cookie, which the browser only sends
to the same origin. `src/api.ts` is the typed client: it adds `X-Requested-With: streamsense`
to every non-GET API request (the API's CSRF check; not on the presigned S3 part uploads) and
turns the API's `{"error": {code, message}, requestId}` envelope into an `ApiError` with
`status` and `code`.
`api.createAnalysis(file, meta, onProgress, signal)` posts the multipart `POST /analyses` with
`XMLHttpRequest` (fetch has no upload progress) and resolves with `{game, job}`.
`src/store.tsx` polls alerts every 5 s, the catalog every 15 s, and active jobs every 1.5 s;
Match Analysis refetches frames on each job update so partial results fill the timeline.
Frames, posters and heat-map overlays render from the API's media URLs; a frame without a
stored image shows a neutral empty box (or a spinner while it is still processing).

## Accounts

The app opens on a sign-in page until `GET /auth/me` succeeds; an expired or revoked session
(any `401`) returns to it, and signing in lands back on the same URL. Create the first admin on
the API host, then add everyone else from **Admin → Users** (`/admin/users`):

```sh
# from ../backend, with the API's STREAMSENSE_API_* settings; prompts for the password
python -m app.users create --email you@example.com --name "You" --role admin
```

| Role | Can |
| --- | --- |
| viewer | Read everything. |
| reviewer | + New Analysis, Re-run, Confirm / Dismiss alerts, add / undo feedback, Export CSV. |
| admin | + Users, Save alert threshold, Queue Fine-Tune. |

Controls a role cannot use are hidden; the API enforces the same rules (`403 forbidden`).
Passwords need 10+ characters. Changing your password (user menu) signs you out everywhere.

## What's in the app

| Route | Screen | Notes |
| --- | --- | --- |
| `/` | Games catalog | Netflix-style rows (Needs review, Live and in progress, Recently analyzed, by sport). Search + Sport / Status / Defect / Camera filters switch to a grid. Empty catalog = "New Analysis" call to action. |
| `/new` | New Analysis | The one way to analyze footage. Drop zone / picker (MP4, MOV, JPG, PNG; type, 2 GB and 60 min checked in the browser, re-checked by the API) + game details (home, away, sport, league, venue, camera, date, start time) + Run Analysis. Upload progress (MB sent / total) with Cancel; on `202` it opens the game's Match Analysis, where the job runs. Recent analyses (`GET /jobs`) below. `/test` redirects here; the red **+** in the nav opens it. |
| `/games/:id` | Match Analysis | Run stats from the job (mean / p95 latency, frames/s, hardware), timeline of sampled frames filling in while the job runs, frame detail with defects, explanation, heat-map toggle (when the API has one), Confirm / Dismiss for alerts, and **model feedback**: Correct / Incorrect on a detection, Flag Missed Issue with defect, severity, optional region click and note. Images show a single-frame result instead of a timeline. "Re-run analysis" (`POST /jobs/match`) for finished, failed or cancelled analyses. |
| `/performance` | Model Performance | Run picker, binary KPIs, per-defect table, calibration curve (all from imported runs; an empty state when there are none), threshold slider preview + Save, and a Human Feedback panel fed by labels from Match Analysis. |
| `/admin/users` | Users (admin) | Name, email, role (inline), active toggle, last sign-in, reset password; Add user form. You cannot demote or deactivate yourself. |
| sidebar | Alerts | Bell in the nav toggles it; badge counts unseen alerts. Open / Reviewed tabs, Confirm / Dismiss (version-checked; a conflict or network error shows the failed-save + retry state and reloads the queue). Click an alert to jump to its frame. |

All state (games, alerts, feedback, jobs, thresholds) lives in the API; nothing is kept in
`localStorage`. With the API's dummy backend, results are synthetic and tagged `dummy@0.1`.

## Fonts

Druk and Siro are licensed. Drop `Druk-Bold.woff2`, `Druk-Medium.woff2`, `Siro-Regular.woff2`
and `Siro-Medium.woff2` into `public/fonts/` and they load automatically; until then the
stacks fall back to Impact / system-ui as the design doc specifies.

## Structure

```
src/
  globals.css        design tokens (@theme) + font-face
  api.ts             typed fetch client for the StreamSense API
  auth.tsx           session state (GET /auth/me), sign-in / sign-out, role checks
  store.tsx          API-backed state + polling: games, alerts, feedback, jobs, threshold, sidebar
  data/format.ts     formatting helpers (titles, match clock, wall clock, sizes, API timestamps)
  data/types.ts      API response shapes (camelCase)
  components/        Nav, AlertsSidebar, GameCard, Timeline, FrameThumb, ui primitives
  pages/             Home, NewAnalysis, MatchAnalysis, ModelPerformance, Users, SignIn
```
