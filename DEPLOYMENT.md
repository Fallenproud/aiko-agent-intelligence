# Deployment readiness — v0.3.1

Status: prepared locally; NOT deployed. Browser widget rendering and hosted persistence are NOT verified.

## Compatible target

Render Python web service + persistent disk. The included render.yaml uses the currently documented 0.5c-512mb compute plan and a 1 GB disk in Frankfurt. Both are billable resources. No such resource has been created.

Netlify's standard functions do not directly run this Python server. Vercel's temporary filesystem does not preserve the app's local SQLite contract. Deploying only HTML there would not verify the backend.

## Pending provider access

Install/connect Render in ChatGPT. Once connected, resolve the intended workspace, repository and compute/storage costs before creating the service. This package has no existing Render service ID or remote source repository.

## Deploy from this directory as repository root

- Build: pip install -r requirements-lock.txt
- Start: python start_hosted.py
- Persistent mount: /var/data
- AIKO_DB: /var/data/aiko.sqlite3
- AIKO_COOKIE_SECURE: 1
- AIKO_PUBLIC_BASE_URL: exact HTTPS deployment origin, or verified RENDER_EXTERNAL_URL supplied by Render
- AIKO_CHATKIT_DOMAIN_KEY: domain key for the registered hosted origin
- Health check: /healthz
- One service instance / one process worker.

The start script derives the canonical origin from provider/runtime configuration, not forwarded browser headers. It checks that the database directory exists; this check does not by itself prove a durable disk is mounted.

The app keeps proxy headers disabled. Client-IP rate limits therefore may be shared behind a provider proxy. This is a limited verification deployment, not production rate-limit readiness.

## Account provisioning

After the service is running, use its runtime Shell (persistent disk available there):

    python manage_users.py kim

This prompts for a new password. Run it again with another username for the isolation test. Do not provision during build/pre-deploy: Render disks are accessible at runtime only. Never commit databases or test passwords.

## Required hosted verification

1. Provider deploy reports success and returns a real URL.
2. /healthz returns status ok; /api/runs/current without a session returns 401.
3. Browser login returns a Secure + HttpOnly session cookie; cross-origin mutation fails.
4. /chat loads the real ChatKit component on the registered domain.
5. A message creates a native ChatKit widget; approval persists and the worker completes.
6. Reload retains the result. Another account cannot access that run or thread.
7. Logout revokes the session. Replaying its cookie fails.
8. Restart the hosted service and confirm account, conversation and event history persist.
9. Check mobile layout and browser console. Capture sanitized evidence.

Do not mark steps as passed without executing them against the deployed service. The local SDK tests remain separate from hosted/browser checks.

References checked for this preparation:
- https://render.com/docs/blueprint-spec
- https://render.com/docs/disks
- https://render.com/docs/web-services
- https://render.com/docs/free
