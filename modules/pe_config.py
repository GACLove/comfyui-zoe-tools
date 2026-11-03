"""Read PE configuration from the process or the custom node's .env file."""

import os
import re
import shlex
from pathlib import Path

DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
PE_KEYS = frozenset({"PROMPT_UPSAMPLER_API_KEY", "PROMPT_UPSAMPLER_BASE_URL", "PROMPT_UPSAMPLER_MODEL"})


def get_config(name):
    if name not in PE_KEYS:
        raise ValueError("Unknown PE configuration key")
    if name in os.environ:
        return os.environ[name].strip()
    try:
        contents = DOTENV_PATH.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""
    result = ""
    for number, line in enumerate(contents.splitlines(), 1):
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if value.startswith(("'", '"')):
            try:
                parts = shlex.split(value, comments=True)
            except ValueError as error:
                raise ValueError(f"Invalid .env value for {name} on line {number}") from error
            if len(parts) != 1:
                raise ValueError(f"Invalid .env value for {name} on line {number}")
            result = parts[0]
        else:
            result = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    return result.strip()


def get_api_key():
    key = get_config("PROMPT_UPSAMPLER_API_KEY")
    if not key:
        raise RuntimeError("Set PROMPT_UPSAMPLER_API_KEY in the environment or custom node .env")
    return key
