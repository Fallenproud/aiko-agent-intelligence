"""Cloudflare Access perimeter validation. App sessions and CSRF remain mandatory."""
import os
import jwt
from jwt import PyJWKClient, InvalidTokenError
from fastapi.responses import JSONResponse

def access_config():
    team = os.environ.get("AIKO_CF_ACCESS_TEAM_DOMAIN", "").strip()
    audience = os.environ.get("AIKO_CF_ACCESS_AUD", "").strip()
    if bool(team) != bool(audience):
        raise RuntimeError("Both AIKO_CF_ACCESS_TEAM_DOMAIN and AIKO_CF_ACCESS_AUD are required.")
    if not team:
        return None
    if not team.endswith(".cloudflareaccess.com") or "/" in team or ":" in team:
        raise RuntimeError("Invalid Cloudflare Access team domain.")
    issuer = f"https://{team}"
    return (issuer, audience, PyJWKClient(f"{issuer}/cdn-cgi/access/certs", cache_jwk_set=True, lifespan=300))

def install_access_boundary(app):
    config = access_config()
    if not config:
        return
    issuer, audience, keys = config

    @app.middleware("http")
    async def verify_cloudflare_access(request, call_next):
        # Render health checks must not require interactive Cloudflare identity.
        if request.url.path == "/healthz" and request.method in ("GET", "HEAD"):
            return await call_next(request)
        token = request.headers.get("cf-access-jwt-assertion", "")
        if not token:
            return JSONResponse({"detail": "Cloudflare Access assertion required"}, status_code=403)
        try:
            key = keys.get_signing_key_from_jwt(token).key
            jwt.decode(token, key, algorithms=["RS256"], audience=audience,
                       issuer=issuer, options={"require": ["exp", "iat", "aud", "iss"]},
                       leeway=30)
        except (InvalidTokenError, ValueError, Exception):
            # Deliberately do not leak signature, key, or identity details.
            return JSONResponse({"detail": "Invalid Cloudflare Access assertion"}, status_code=403)
        return await call_next(request)
