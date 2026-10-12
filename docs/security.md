# Security and privacy

The detailed design (§§2.4 and 3.6–3.8) sets the requirements below. These protections still need
to be built and tested. The current local setup has no real users, uploads, client footage or
hosted services. It is not a production security system.

## Login and access

Use a managed login service through OIDC, a standard sign-in method. Protect the login flow with
PKCE and check its issuer, audience, state and nonce values. The [glossary](glossary.md) explains
the main abbreviations; the developer implementing login must also follow the provider's guidance.

Webmasters invite users; there is no public self-registration by default. The team and Vijay are
the intended webmasters, but setup does not create these accounts. Save only the account details
needed by the app, not passwords or provider tokens.

A successful login is not permission to see every file. Each request must check that the account
is active and may access the requested asset, job, frame, alert or media. Guessing an ID must not
grant access. The server determines the user and reviewer from the session, not an ID supplied by
the browser. Only webmasters manage accounts, permissions and published thresholds.

Login sessions must expire and end on logout. Changed permissions must apply immediately to
existing sessions and future requests. Use server-side sessions and cookies marked `Secure`,
`HttpOnly` and `SameSite`, plus CSRF protection for requests that change data. The team still needs
to choose the provider, session settings and detailed access rules (D-02).

The local `/health` route only says that the server is running and reveals no private data.
Decide separately whether to expose a health route in deployment; it does not create an exception
for private application data.

## Uploading, processing and viewing footage

- Upload directly to private storage using short-lived, limited permission.
- Agree on file formats, codecs, sizes and durations. Check the actual file contents, not just
  its extension or the browser's description. Decode files separately from API requests.
- Do not download files from arbitrary URLs supplied by users.
- Check access every time media is viewed. Use `Cache-Control: private, no-store` so private
  media responses are not kept in browser/shared caches.
- Give services only the access they need. Encrypt connections and stored data, and confirm
  that the selected hosting services support the required network restrictions (D-03).
- Keep saved models private. Never log footage, raw labels, passwords, cookies, signed viewing
  links or identifying client metadata.
- Uploading a video or reviewing an alert does not give permission to use it for model training.

## What can go in GitHub?

Use made-up data for tests and examples. Keep client media, metadata rows, labels, predictions,
saved models, source PDFs and meeting recordings outside the repository. Review files and their
contents before publishing; `.gitignore` alone cannot prevent accidental disclosure.

Automated GitHub checks must work without client data or credentials. Permission to use AI tools
does not remove these restrictions. A public code repository does not make client footage public.

## Keeping and deleting data

Before real footage is uploaded, agree with Vijay on how long to keep originals, frames, heat maps,
predictions, backups and experiment files (D-06). No retention period has been approved by this setup.

Deleting an asset must immediately prevent further viewing and arrange removal of its related
files and records. Keep only the allowed anonymous audit information. The team must decide how
that works with database links to user accounts before implementing deletion.

## Checks required as features are built

Test that users cannot access someone else's files, revoked accounts lose access, unwanted
cross-site requests are rejected, and invalid/oversized files fail clearly. Also test conflicting
reviews, repeated requests, failed analysis, missing heat maps, private cache settings and deletion.
The current two starter tests do not prove these protections work.
