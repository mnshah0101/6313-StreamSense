# How the screens, server and model communicate

An API is the interface the screens use to ask the server for work or results. Each endpoint
below is one request address. These requests come from Detailed Design V1 §3.6 and are **not
implemented**, except for the local `GET /health` check. The final hosted URL prefix is still
undecided. Deployed connections must use HTTPS and exchange structured JSON data.

## Requests the screens will make

| Endpoint | Input / output | Required checks |
| --- | --- | --- |
| `POST /assets` | Upload metadata → asset ID and short-lived upload permission | Active account, permitted formats/size/duration, owner from session; no arbitrary URL fetch |
| `POST /analysis-jobs` | Asset ID, selected model ID, analysis settings → 202 with job ID/status | Permission to analyze the checked file/model; repeated requests must not create duplicate jobs |
| `GET /analysis-jobs/{job_id}` | Status/progress or safe failure code | Job/asset access; no internal exception paths |
| `GET /analysis-jobs/{job_id}/frames` | Paginated timestamped frame results | Job/asset access; results may arrive before job completion |
| `GET /alerts` | Queue with permitted state filters | Review permission and asset scope |
| `POST /alerts/{alert_id}/review` | `decision`, `expected_version` → saved review | Reviewer identified from login; save changes together; return 409 if the alert changed |
| Threshold publication (path pending) | New immutable model-bound threshold | Webmaster only; validation-run evidence, model consistency |

Protect requests that change data with CSRF checks. A creation or review request has a unique
key so repeating it does not duplicate the action. Give every request an ID for troubleshooting.
Errors should return a consistent safe code and that ID, never private file keys, passwords,
internal error details or file paths. The exact error format, duplicate-request time limit,
result-page navigation and upload-completion steps still need decisions (D-05/D-07/D-09).
Rejected requests must not reveal whether private files exist. Choose and test a consistent
403/404 response rule during the login/access task.

## Example frame result

This example shows the fields a frame result will contain. Its values are made up, not measured:

```json
{
  "schema_version": "1.0",
  "job_id": "00000000-0000-4000-8000-000000000001",
  "frame_id": "00000000-0000-4000-8000-000000000002",
  "model_id": "00000000-0000-4000-8000-000000000003",
  "timestamp_ms": 5000,
  "quality_issue": true,
  "issue_score": 0.92,
  "defects": [
    {"name": "blur", "severity": null, "severity_source": "unavailable", "location_text": null}
  ],
  "latency_ms": 740,
  "heatmap_available": false
}
```

Scores are nullable when unavailable, not fabricated probabilities. Defect names remain flexible
text. `quality_issue=false` requires no detected defects; failed parsing/inference is a separate
failure, never `false`. Image-level severity cannot populate per-defect severity. Missing
localization is shown explicitly. Saved records identify the model, settings and alert policy used. Reviewing an alert never
changes the model's answer.

## Connections behind the screens

- Server → database: check access, keep updates short and save each review as one complete change.
  Repeating a request must not duplicate it.
- Worker → database: claim one job safely, save frame results as they arrive and limit retries.
- Worker → model adapter: send the decoded frame and fixed model/settings, then check the result
  before saving it. The translation from research results needs its own tests; see `ml-integration.md`.
- Server/worker → private media storage: read and write files using private keys. The browser gets
  only approved upload/viewing methods, never the service's reusable credentials.

The analysis must run as a saved background **job**. Writing `async def` on a Python route does
not move the work into a separate worker. The design calls for a separately hosted worker,
not a temporary background task inside the web server.
