# Short glossary

You do not need to memorize these terms. This page is a reference when reading the detailed documents.

| Term | Meaning in this project |
| --- | --- |
| API / endpoint | The server interface the app calls to request work or retrieve results. An endpoint is one address, such as `/analysis-jobs`. |
| Asynchronous job | Work that continues in the background after the server responds. Users can check progress without keeping one request open. |
| Worker / inference | A separate process runs the model on frames. Running a trained model to produce results is called inference. |
| Database schema / migration | The schema defines tables, fields and rules. A migration is a saved script that creates or changes that structure. |
| UUID, PK, FK | A UUID is a record ID. A primary key (PK) identifies a row; a foreign key (FK) links it to another row. |
| JSON / JSONB | A structured text format for exchanging data. JSONB is PostgreSQL's way of storing and checking that data. |
| Authentication / authorization | Authentication checks who someone is. Authorization checks what that person is allowed to do. |
| OIDC / PKCE / CSRF | OIDC is a standard login method; PKCE helps protect that login flow. CSRF protection prevents another website from making changes through a user's session. |
| Lease / idempotency | A lease lets one worker claim a job for a limited time. Idempotency prevents a repeated request from creating duplicate work. |
| Provenance / immutable | Provenance records where a result came from, including its model and settings. An immutable record cannot be changed after creation. |
| Precision / recall | Precision: how many flagged issues are real. Recall: how many real issues the model catches. |
| Validation / locked test set | Validation data helps choose settings. The locked test set is kept separate for the final evaluation. |
| Threshold / calibration | A threshold is the cutoff used to raise an alert. Calibration here means choosing that cutoff using validation results. |
| Checkpoint / adapter | A checkpoint contains saved model weights. An adapter connects a particular model to the shared interface. |
| Lockfile / CI | A lockfile records exact software dependency versions. Continuous integration (CI) runs automated checks on GitHub. |
| Scaffold / synthetic data | A scaffold is the starter setup, before product features are built. Synthetic data is made-up test data, not client footage or labels. |
