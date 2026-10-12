# How the application will work

## Purpose and current status

Users will upload sports footage, start an analysis, inspect frame-by-frame results and confirm
or dismiss image-quality alerts. The October 9 meeting adds a demo that shows several uploaded
videos with timelines that grow as results arrive. It simulates live monitoring; it does not
connect to production streams or shut them down.

The model research already exists in a separate repository. This app currently has only a
starter development setup. The sections below describe what we plan to build.

## Main parts

| Part | Technology and job | Important limit |
| --- | --- | --- |
| Web screens | React + TypeScript; uploads, progress, timelines, alerts and metrics | Never contain database or storage passwords |
| Application server | FastAPI; checks login/access and handles jobs and reviews | Does not decode videos or run the model during a web request |
| Background worker | Python on a GPU; reads videos, samples frames and runs the model | Works separately from the web server; does not need a public model endpoint |
| Database | PostgreSQL; stores records, relationships, job status and reviews | Stores file references, not video or model files |
| Private media storage | Vercel Blob is the proposed service for footage, frames and heat maps | Every viewing request needs an access check |
| Login service | A managed OIDC provider, still to be selected | Webmasters invite users; app permissions are checked by our server |
| Saved models | Private model files and version records available to the worker | Every job records exactly which model and settings it used |
| Research tools | Existing PyTorch/Hugging Face/Hydra code | Separate setup and data splits; reviews do not automatically become training data |

The detailed design proposes Vercel for the web app and API, a managed PostgreSQL database,
and separate GPU hosting supplied by the client. PACE is already used for experiments. EC2 is
one possible future host, not a confirmed service. Before deployment, the team must check costs,
network access and whether the selected services meet the privacy requirements (D-03).

## What happens during analysis

1. The server checks who the user is and whether they may upload and analyze the footage.
2. The file uploads directly to private storage. The system checks its size, format and contents.
3. The server saves an analysis job with its asset, model and settings. It returns a job ID
   immediately with HTTP 202, meaning the work has been accepted.
4. The worker claims the job so two workers do not process it at once. It reads the video,
   samples roughly one frame every five seconds, and runs the model in batches.
5. Results are saved as processing continues. The screen requests new results and updates the
   timeline without waiting for the whole match to finish.
6. The job finishes as succeeded, failed or cancelled. A failed model run is never shown as a clean frame.

Job states: `queued`, `running`, `succeeded`, `failed`, `cancelled`.
Planned transitions are queued → running/cancelled, then running → succeeded/failed/cancelled.
The team still needs to decide how long a worker can claim a job and how retries work (D-07).
The first database task stores the possible states; it does not build the worker or state changes.

## What happens during review

An alert links to the original model result and the threshold used to raise it. When a user
confirms or dismisses it, the server saves the decision, reviewer and time together with the
updated alert status. If someone else has already changed the alert, the server returns a
conflict instead of silently replacing their decision.

The model's original result stays unchanged. Confirm means the user reviewed it as a real issue;
it does not mean a repair crew was contacted. Reviews do not automatically change training labels.

## Performance and the demo

The target is under five seconds for one sampled frame on stated hardware, such as an NVIDIA L4.
It is not a promise to process an entire video in five seconds. Tests must report the model,
hardware, batch size, memory use, speed and where processing time is spent. CPU setup checks
cannot prove GPU performance.

The roughly 100-stream figure still needs clarification: one meeting summary describes a target,
while the research report describes 100–120 streams as a reference result. Record actual test
results and agree on the acceptance target with Vijay (D-04).

The demo should show several video jobs and growing timelines. The team still needs to settle
video count, playback speed, how screens receive updates and how quickly they should update (D-08).
The inspected Figma prototype shows completed results for one match.

## Outside the initial app

Production-stream connections, Slack/crew delivery, automatic shutdown, game-state detection,
payments, support for multiple client organizations and automatic retraining are out of scope.
A model that reasons across several frames is not currently required. Heat maps, switching between
models and skipping similar frames remain optional experiments.
