# Dataset V1 schema guide

Run `python scripts/inspect_labels.py +experiment=e01_audit` to create the local
`docs/DATA_SCHEMA.md`, aggregate JSON counts, a findings CSV, and a run record.
The generated report is ignored because it contains client-derived information.

The input is a JSON object keyed by `<game_id>/frame_NN.jpg`. Each value is a label
object with required `decision`, `source`, `term`, and `updated_at`; optional fields
are `description` and `severity`.

| Field | Meaning / provisional handling |
| --- | --- |
| `decision` | `valid` is positive; `not` is negative; `duplicate` is audit-only |
| `term` | Comma-separated labels; strip whitespace, lowercase, preserve raw provenance |
| `severity` | Integer 1–5; absence on an issue row is masked by default |
| `source` | `prefill` or `user`; default weights 1.0 each |
| `description` | Optional explanation target, never an input by default |
| `updated_at` | Retained provenance string |

Inspection counts decisions, sources, raw term strings, individual normalized raw
terms, positive-only terms, severity values, field presence, and source by decision.
Duplicate rows are included in raw totals; their missing/present files and nonempty
terms are counted separately. This is not yet a full image audit or a usable manifest.

Open questions remain the meaning of `not`, term-to-crew mappings (especially low
contrast and saturation), image versus per-defect severity, prefill quality, and
the missing-severity policy. Every mapping is provisional in `conf/data/taxonomy.yaml`.
