# Security and privacy specification

Source: Detailed Design V1 §§2.4, 3.6–3.8. These are planned controls. The preparation scaffold
has no real accounts, uploads, client data or hosted services and is bound to localhost.
It is not a production authentication or security implementation.

## Identity and authorization

Use a managed OIDC provider, authorization code flow with PKCE, and validate issuer, audience,
state and nonce. Webmasters invite/provision accounts; no public self-registration by default.
Only active, explicitly authorized accounts may read application data or media. The team and
Vijay are the intended webmasters, but no accounts or credentials are seeded by preparation.
Store the provider subject and minimum account information, not passwords/provider tokens.

Use server-side sessions with Secure, HttpOnly, SameSite cookies, expiry and server-side logout.
Require CSRF protection for state changes. Role/permission changes must affect future requests
and existing sessions immediately. Provider, session lifetime/store and invitation policy are D-02.

Authenticate every deployed data route and authorize the full chain from asset to job, frame,
prediction, alert and media. An ID is not permission. Browser-supplied owner/reviewer IDs are not
trusted. Regular users receive explicit analysis/review and asset access; only webmasters can
manage accounts, permissions and threshold publication. Detailed permission/grant schema is D-02.
The scaffold health endpoint is local liveness only and returns no private state; production
health-route exposure must be decided with deployment, rather than bypassing the data-route rule.

## Media and processing

- Upload directly into private storage with short-lived, bounded authorization.
- Enforce an approved format/codec/size/duration list, verify actual decoded content, and
  isolate decoding from API requests. Never trust an extension or MIME header alone.
- Do not fetch user-supplied arbitrary URLs. Do not expose storage credentials or internal keys.
- Check authorization each time private media is served, with `Cache-Control: private, no-store`.
- Use least-privilege service credentials and encrypted connections/storage. Validate that the
  selected providers can meet the desired network isolation before deployment (D-03).
- Keep checkpoints private alongside the worker. API logs must not contain footage, raw labels,
  cookies, signed links, credentials or identifying client metadata.
- Never feed uploaded footage, dismissed alerts or human reviews into training automatically.

## Repository and test data

Use synthetic fixtures and generic examples. Keep original source PDFs, meeting recordings,
client media, metadata rows, predictions, model checkpoints and private reports outside Git.
`.gitignore` provides a convenience boundary only; review staged paths and content before push.
CI must operate without client credentials or datasets. A public source repository does not make
its associated client data public. AI tooling permission does not override these data boundaries.

## Retention and deletion

Client-approved periods must cover originals, sampled frames, overlays, predictions, backups
and experiment artifacts. The periods are unresolved (D-06); no production media ingestion is
approved by this setup. Deletion immediately blocks viewing and schedules coordinated removal
of associated files/rows, preserving only appropriately anonymized audit evidence. The final
schema must resolve actor-FK/anonymization behavior before implementing deletion.

## Required verification before relevant features ship

Test unauthorized cross-asset access, revoked accounts/sessions, CSRF rejection, upload format
spoofing and resource limits, stale/concurrent reviews, duplicate requests, failed inference,
missing overlays, private cache headers, and deletion/access revocation. Test each when that
feature is implemented; do not claim the scaffold already passes these product controls.
