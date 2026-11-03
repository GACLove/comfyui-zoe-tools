"""Discover models without exposing the API key to the ComfyUI browser."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .pe_config import get_api_key, get_config

DEFAULT_BASE_URL = "https://tokenhub.sensetime.com/v1"


def resolve_base_url(value=""):
    result = (
        value.strip() or get_config("PROMPT_UPSAMPLER_BASE_URL") or DEFAULT_BASE_URL
    ).rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models"):
        if result.endswith(suffix):
            result = result[: -len(suffix)].rstrip("/")
            break
    parsed = urlsplit(result)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid PE base URL")
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_models(base_url=""):
    target = resolve_base_url(base_url)
    configured = resolve_base_url()
    # A browser request must not send the server's key to an arbitrary host.
    if target not in {configured, DEFAULT_BASE_URL}:
        raise ValueError("Set PROMPT_UPSAMPLER_BASE_URL to this URL before refreshing models")
    key = get_api_key()
    request = Request(
        target + "/models", headers={"Authorization": "Bearer " + key, "Accept": "application/json"}
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Model list request failed: HTTP {error.code}") from error
    except (URLError, OSError) as error:
        raise RuntimeError("Model list request failed; check the configured base URL") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Model list response must contain a data array")
    models = [
        item["id"]
        for item in payload["data"]
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    ]
    if not models:
        raise ValueError("The model list is empty")
    return list(dict.fromkeys(models))
