# API and component interfaces

These endpoints describe planned behavior from Detailed Design V1 §3.6. Except for the local
`GET /health` scaffold, they are **not implemented**. Paths below are application-relative;
final deployment routing/prefix is not yet selected. HTTP JSON uses HTTPS when deployed.

## Planned browser API

| Endpoint | Input / output | Required checks |
| --- | --- | --- |
| `POST /assets` | Upload metadata → asset ID and short-lived upload permission | Active account, permitted formats/size/duration, owner from session; no arbitrary URL fetch |
| `POST /analysis-jobs` | Asset ID, selected model ID, analysis settings → 202 with job ID/status | Analysis permission, access to validated asset/model; idempotent creation |
| `GET /analysis-jobs/{job_id}` | Status/progress or safe failure code | Job/asset access; no internal exception paths |
| `GET /analysis-jobs/{job_id}/frames` | Paginated timestamped frame results | Job/asset access; results may arrive before job completion |
| `GET /alerts` | Queue with permitted state filters | Review permission and asset scope |
| `POST /alerts/{alert_id}/review` | `decision`, `expected_version` → saved review | Session-derived reviewer; transaction; 409 for stale version |
| Threshold publication (path pending) | New immutable model-bound threshold | Webmaster only; validation-run evidence, model consistency |

State-changing requests require CSRF protection. Creation/review requests carry idempotency
keys; all requests receive request IDs. Errors have stable safe codes and a request ID, never
storage keys, credentials, stack traces or filesystem paths. The exact error envelope,
idempotency expiry, page cursor and upload-finalization contract remain D-05/D-07/D-09.
Unauthorized requests must not expose whether private resources exist; settle a consistent
403/404 policy in the auth task and test it.

## Versioned frame result

Illustrative contract, not a measured prediction:

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
localization is shown explicitly. Provenance includes model/configuration and policy versions
in persisted records; review never changes the model's answer.

## Internal boundaries

- API → database: short transactions with authorization; atomic review and idempotency.
- Worker → database: atomic lease claim, incremental frame/result persistence, bounded retries.
- Worker → model adapter: decoded frame + fixed model manifest + inference config → validated
  result. Model output must pass validation before persistence. Research adapter translation
  is defined conceptually in `ml-integration.md` and needs its own contract tests.
- API/worker → private media repository: service-side object-key operations. Browser receives
  only authorized upload methods/media routes, never reusable service credentials.

Asynchronous **jobs** are required; merely declaring a Python route `async def` does not
move inference into a durable worker. Do not use an in-process web request background task
as a substitute for the separately hosted analysis worker in the design.
