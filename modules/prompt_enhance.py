"""ComfyUI interface for the Router split-fix3 prompt enhancer."""

import argparse
import json

from . import t2i_pe_core as pe
from .base import NODE_CATEGORY
from .model_discovery import resolve_base_url
from .pe_config import get_api_key, get_config


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


class RouterPromptEnhance:
    @classmethod
    def INPUT_TYPES(cls):
        text = lambda value: ("STRING", {"default": value, "multiline": True})  # noqa: E731
        return {
            "required": {
                "user_prompt": text(""),
                "mode": (["full", *pe.SHARD_KEYS],),
                "system_prompt": text(pe.SYSTEM_PROMPT),
                "shard_a_subjects": text(pe.A_SUBJECTS_PROMPT),
                "shard_b_spatial": text(pe.B_SPATIAL_PROMPT),
                "shard_c_direction": text(pe.C_DIRECTION_PROMPT),
                "shard_d_delivery": text(pe.D_DELIVERY_PROMPT),
                "canvas_mode": (["auto", "explicit"],),
                "width": ("INT", {"default": 2048, "min": 1, "max": 32768}),
                "height": ("INT", {"default": 2048, "min": 1, "max": 32768}),
                "aspect_ratio": ("STRING", {"default": "1:1"}),
                "base_url": ("STRING", {"default": ""}),
                "model": ("STRING", {"default": ""}),
                "max_tokens": ("INT", {"default": pe.DEFAULT_MAX_TOKENS, "min": 1, "max": 131072}),
                "reasoning_effort": ("STRING", {"default": pe.DEFAULT_REASONING_EFFORT}),
                "service_tier": ("STRING", {"default": pe.DEFAULT_SERVICE_TIER}),
                "timeout": ("INT", {"default": 300, "min": 1, "max": 3600}),
                "retries": ("INT", {"default": 3, "min": 1, "max": 10}),
                "run_id": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("enhanced_prompt", "debug_report", "shards_json")
    FUNCTION = "enhance"
    CATEGORY = NODE_CATEGORY

    def enhance(
        self,
        user_prompt,
        mode,
        system_prompt,
        shard_a_subjects,
        shard_b_spatial,
        shard_c_direction,
        shard_d_delivery,
        canvas_mode,
        width,
        height,
        aspect_ratio,
        base_url,
        model,
        max_tokens,
        reasoning_effort,
        service_tier,
        timeout,
        retries,
        run_id,
    ):
        if not user_prompt.strip():
            raise ValueError("user_prompt must not be empty")
        if not system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        base_url = resolve_base_url(base_url)
        model = model.strip() or get_config("PROMPT_UPSAMPLER_MODEL") or pe.DEFAULT_MODEL
        key = get_api_key()
        templates = dict(
            zip(
                pe.SHARD_KEYS,
                (
                    shard_a_subjects,
                    shard_b_spatial,
                    shard_c_direction,
                    shard_d_delivery,
                ),
            )
        )
        if mode == "full":
            settings = argparse.Namespace(
                api_key_env="PROMPT_UPSAMPLER_API_KEY",
                base_url=base_url,
                model=model,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                service_tier=service_tier,
                timeout=timeout,
                retries=retries,
                output_width=width if canvas_mode == "explicit" else None,
                output_height=height if canvas_mode == "explicit" else None,
                aspect_ratio=aspect_ratio if canvas_mode == "explicit" else None,
            )
            if canvas_mode == "explicit" and not aspect_ratio.strip():
                raise ValueError("aspect_ratio is required for explicit canvas")
            result = pe.enhance_instruction(
                user_prompt, settings, api_key=key, system_prompt=system_prompt, templates=templates
            )
            shards = result.pop("shards")
            enhanced_prompt = result.pop("prompt_text")
            result.pop("prompt")
            result["canvas_mode"] = canvas_mode
            result["note"] = (
                "For text_led_graphic, lighting and cinematography are replaced "
                "and person fields in subjects are cleared. Explicit canvas overrides "
                "the B shard. The caption is derived during merge."
            )
            return enhanced_prompt, _json(result), _json(shards)
        if mode not in pe.SHARD_KEYS:
            raise ValueError(f"unknown PE mode: {mode}")
        shard = pe.run_shard(
            shard=mode,
            instruction=user_prompt,
            api_key=key,
            base_url=base_url,
            model=model,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
            service_tier=service_tier,
            timeout=timeout,
            retries=retries,
            require_canvas_selection=canvas_mode == "auto",
            system_prompt=system_prompt,
            template=templates[mode],
        )
        report = {
            "status": "partial",
            "mode": mode,
            "model": model,
            "base_url": base_url,
            "message": "Single shard only; no complete enhanced prompt was produced.",
        }
        return "", _json(report), _json({mode: shard})
