# Cloudflare Access M0.2 — controlled cutover

This branch prepares JWT enforcement but does not change production.

## Verified Cloudflare configuration

- Protected hostname: `aikov.daycostra.com`
- Access application ID: `940579e2-d423-47f8-bc9f-a0044abdf42a`
- `AIKO_CF_ACCESS_AUD=2ec2fc1684c68383b1782b2db7787ce30ae88149e56d7283ad44828686860346`
- `AIKO_CF_ACCESS_TEAM_DOMAIN=lumina-diy-pages.cloudflareaccess.com`
- Access allow policy: `mrevensen94@gmail.com` only

These are non-secret configuration values. Do not set the two environment variables until the application code is deployed and the hostname is ready for cutover.

## Required deployment sequence

1. Review and merge this branch; run tests and verify the existing Render origin still works.
2. Add `aikov.daycostra.com` as a custom domain in the existing Render service. Read Render's exact verification/CNAME instructions before modifying DNS.
3. Create the exact required DNS records in Cloudflare, with appropriate proxy/TLS settings. Confirm Render custom domain and TLS are verified.
4. Set `AIKO_PUBLIC_BASE_URL=https://aikov.daycostra.com`, `AIKO_CF_ACCESS_AUD`, and `AIKO_CF_ACCESS_TEAM_DOMAIN` together in Render. Do not switch the canonical origin prematurely.
5. Verify the Access login for the approved administrator; check app login, ChatKit, CSRF, sessions and DB persistence.
6. Confirm absent, forged, expired, wrong-issuer and wrong-audience JWTs fail; test direct Render-hostname bypass and Host header handling.
7. Disable the default `.onrender.com` hostname through Render's supported control only after all tests pass. Keep rollback procedure available.

**Important:** This connector currently has no Render custom-domain management or Render hostname-policy update operation. These steps must not be reported as completed without verification. Render health probes call `/healthz`, which the JWT middleware deliberately exempts; that endpoint returns only basic health metadata.

## Rollback

Restore the previous Render environment variables and deploy version, keep the Render hostname enabled until verification is complete, and remove or revert the new Cloudflare DNS record if needed.
