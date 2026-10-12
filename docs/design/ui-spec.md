# UI specification

Reference: [StreamSense mid-fidelity prototype](https://www.figma.com/proto/m22oT1kKlNysFpEaeVg8NJ/StreamSense-Mid-Fi-Prototype---Parallax-6313?node-id=12-3282).
Browser inspection: October 11, 2026. This describes planned screens; the runnable frontend
currently shows only an environment-preparation page.

## Layout and presentation

The prototype uses a light desktop interface, a shared top navigation, card-based results,
clear text headings and compact defect/severity labels. Navigation: Alerts, Test a Stream or
Clip, Match Analysis, and Model Performance. Preserve that structure when implementing.
Exact typography, spacing tokens and responsive breakpoints have not been extracted/approved;
choose them in the UI task and validate with the prototype rather than claim pixel-perfect fidelity.
Use semantic controls, visible keyboard focus, text labels for status, and accessible error/progress
announcements. Color alone must not convey good/bad or review state.

## Screens and states

| Screen / inspected node | Required behavior | Important non-success states |
| --- | --- | --- |
| Alert queue `12:3282` | Open/Reviewed views, source/frame preview, detected defects, available severities, Confirm/Dismiss | Empty queue, loading, unauthorized, failed save; preserve original prediction |
| Alert detail `12:4623` | Exact frame, defect list, source time, region text if validated, review controls | Missing severity/location, unavailable media, review conflict |
| Heat map on `12:4671` | Toggle aligned overlay for supported spatial defects; return to original view | Explicit unavailable/unsupported/failed message; no synthetic overlay masquerading as inference |
| Test a Stream or Clip `12:4724` | Select/drop image or clip, validate selection, initiate async analysis; whole-match entry | Unsupported/corrupt/oversized media, upload failure, queued/running/failed job |
| Match Analysis `12:5736` | Timestamped markers and frame details; hardware-labelled run statistics when available | Partial progress, failed frame, cancelled/failed job, no results yet |
| Model Performance `12:6263` | Named run/split, binary/per-defect metrics, calibration, authorized threshold controls | Missing metrics/support, unavailable severity control, incompatible model/run |

The flow list also exposes a dismiss-failure demo; that branch was not fully inspected.
Its existence does not establish implemented error handling.

## Prototype-to-implementation corrections

- Confirm records a human review only. Crew routing/Slack is outside initial application scope.
- Prototype severity 1–5 values are examples. Show **Unavailable** until validated per-defect
  severity exists; severity-based alert suppression stays off in that state (S2 §3.7).
- Dashboard precision/recall, timeline latency and heat maps are illustrative. Read real values
  only from recorded outputs and label validation versus final-test results accurately.
- Threshold previews use validation data, never the final test set. Only webmasters publish
  an immutable version tied to its model and calibration run.
- The upload screen lists JPG/PNG and MP4/MOV clips up to 60 seconds; S2 lists MP4 and a full-match
  path. Accepted codecs, MOV support, byte limits and clip/match limits must be settled (D-05).
- At least one inspected timeline example uses frame numbering that does not precisely align
  with its time annotation. Derive actual time from stored `timestamp_ms`, not sample labels.
- The October 9 requirement extends the completed single-match prototype to multiple videos
  and growing timelines. Do not claim this behavior was demonstrated by the inspected prototype.

## Later demo extension

Allow users to follow more than one uploaded video job and see incremental, correctly linked
frame results. Keep each job's source, model, progress and failure state visible. Do not promise
instant processing of a whole match. Final concurrency count, pacing, progress update transport,
and load targets require D-08 before implementation. A simulated stream is explicitly labelled
as a demonstration using uploaded videos.
