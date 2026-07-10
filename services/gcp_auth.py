"""Google-signed OIDC ID token minting for Cloud Run service-to-service auth."""

import httpx
import google.auth.transport.requests
import google.oauth2.id_token

_request = google.auth.transport.requests.Request()


def mint_id_token(audience: str) -> str:
    """Mint an OIDC ID token bound to `audience` (target service base URL).

    Uses ADC locally or the runtime service account on Cloud Run.
    google-auth caches tokens internally for their lifetime (~1h).
    """
    return google.oauth2.id_token.fetch_id_token(_request, audience)


class IdTokenAuth(httpx.Auth):
    """httpx auth flow that attaches `Authorization: Bearer <id-token>` per request."""

    def __init__(self, audience: str):
        self.audience = audience

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {mint_id_token(self.audience)}"
        yield request


def is_cloud_run_url(url: str) -> bool:
    """True for Cloud Run endpoints (need ID-token auth). False for localhost / bare hosts (skip)."""
    return url.startswith("https://") and ".run.app" in url
