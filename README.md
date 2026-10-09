# Deployment preparation v0.3.1

See DEPLOYMENT.md for the hosted configuration, remaining connection and verification gates.
The application remains based on v0.3; the following describes its local use.

# AIKO Agent Intelligence v0.3 — Auth + ChatKit

Authenticated browser → FastAPI → owner-scoped SQLite → native ChatKit card/action → durable decision → simulated tool.

This is a local development milestone, not a production release.

## Windows setup (PowerShell)

Requires Python 3.12+. Extract the ZIP and open its aiko-runtime-v0.3 directory:

    py -3.12 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
    .\.venv\Scripts\python.exe manage_users.py kim
    .\.venv\Scripts\python.exe -m uvicorn app:create_app --factory --host 127.0.0.1 --port 8000

The provisioning command prompts for a password (12–256 characters). No default credentials are bundled. Run it again with a different username to create a second account.

Open http://127.0.0.1:8000, log in, then select “Åpne ChatKit”. Send “Status?” to create a thread and receive the native approval widget. Approve or reject there, then open the run overview to inspect persisted events. A thread remains bound to its original run, even when a new demo run becomes current.

Linux/macOS: use python3 to create the venv and .venv/bin/python in place of the Windows Python path above.

## Delivered

- Password hashing using scrypt with per-account random salts.
- Opaque session cookies: HttpOnly, SameSite=Strict, eight-hour expiry. Only token hashes are stored server-side.
- Server-side session revocation on logout; CSRF-token checks for authenticated mutations.
- Local login rate limit (five attempts per client IP per minute).
- Owner enforcement for run reads, decisions, ChatKit threads, items, cursors and thread lists.
- Real openai-chatkit 1.6.5 server endpoint, streamed native widgets and native widget actions.
- ChatKit SQLite store implements thread and item persistence plus pagination.
- Each thread has a server-owned run binding. Browser metadata cannot choose another user's run.
- Widget action payloads must match a persisted widget and its bound run.
- Original v0.2 transaction, version and idempotency protections remain.
- The ordinary AIKO overview uses the authenticated API. /chat uses OpenAI's ChatKit web component with a CSRF-aware custom fetch.

## Verified

Run:

    .\.venv\Scripts\python.exe -m unittest -v

12 tests passed in the development environment. Coverage includes unauthenticated access, CSRF, foreign-owner reads and approvals, session expiry/logout, login limiting, actual ChatKit streaming with a stored native widget, widget approval/retry, forged widget payloads, foreign-thread access, restart persistence, concurrent conflicting decisions, rejection and preserving history.

JavaScript syntax was checked. Native web-component rendering and full browser end-to-end operation have NOT been verified. The browser widget loads from OpenAI's CDN and needs internet access. local-dev is the initial domain key; the page exposes a domain-key input on client errors. Registered deployments may require an allowed domain and domain key.

The pinned SDK emits deprecation warnings for named widget classes. These are supported by the tested version; migration to WidgetTemplate is a future compatibility task.

## Honest boundaries

- Conversation responses are deterministic status cards, not model inference. No OpenAI API key is needed for this implemented server path. No API model calls are made.
- Evidence validation remains simulated. The database decision and ChatKit transport are real.
- No file uploads, speech or attachments are enabled.
- No OIDC/SSO, account recovery, password-change UI, organization roles, tenant administration or production security certification is implemented.
- Local password accounts are a development identity solution. Bind only to 127.0.0.1. HTTPS and Secure cookies (AIKO_COOKIE_SECURE=1), deployment-aware origins, production identity and operational hardening are required before public access.
- The local IP login limiter is not a distributed production rate limiter.
- SQLite remains the local storage choice. There is no production scaling claim.
- Prior v0.2 data is not automatically assigned to a user. v0.3 defaults to a separate aiko-v03.sqlite3 database. Legacy runs have no owner mapping and remain inaccessible if an older database is supplied.
- Native ChatKit approval does not claim general exactly-once execution of external tools. The current atomic worker only simulates a tool.
- No public deployment was created. The preceding Sites quota restriction remains unresolved.

## Configuration

AIKO_DB: database path; defaults to aiko-v03.sqlite3 beside app.py. Use the same value for manage_users.py and the server.
AIKO_COOKIE_SECURE=1: HTTPS-only cookies. Keep unset for the documented loopback HTTP development flow.

Do not bundle real account databases, session cookies or API secrets in shared packages.

API schema: http://127.0.0.1:8000/docs

## Next milestone

Verify the actual ChatKit browser experience and domain configuration. Then add a selected model provider and a real, narrowly scoped evidence tool, with durable job execution, failure/retry semantics and provenance. User identity and resource checks must stay in the backend regardless of model output.

References:
- https://developers.openai.com/api/docs/guides/custom-chatkit
- https://developers.openai.com/api/docs/guides/chatkit-actions
- https://developers.openai.com/api/docs/guides/chatkit-widgets
