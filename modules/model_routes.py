"""ComfyUI API for model discovery."""

import asyncio
import logging

from aiohttp import web
from server import PromptServer

from .model_discovery import get_models

logger = logging.getLogger("Router Prompt Enhance")


@PromptServer.instance.routes.post("/zoe/router-pe/models")
async def router_pe_models(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("base_url", ""), str):
            raise ValueError("Invalid request")
        models = await asyncio.to_thread(get_models, payload.get("base_url", ""))
        return web.json_response({"models": models})
    except (ValueError, RuntimeError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception:
        logger.exception("Model discovery failed")
        return web.json_response({"error": "Model discovery failed"}, status=500)
