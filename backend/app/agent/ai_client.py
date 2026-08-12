"""Unified AI client for the university agent.

Gemini is the default provider. This version uses the current Google GenAI SDK
(`google-genai`) first, with a REST fallback. OpenAI remains optional only when
AI_PROVIDER=openai.
"""

from __future__ import annotations

import os
import json
from typing import Optional, Any

import requests

try:  # Current Gemini SDK: pip install google-genai
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except Exception:  # Keep app booting even before requirements are installed.
    genai = None  # type: ignore
    types = None  # type: ignore


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-2.5-flash-lite"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


def _env_timeout(timeout_env: str, default_timeout: int) -> int:
    """Read timeout from requested env var, then matching Gemini/OpenAI aliases."""
    candidates = [timeout_env]
    if timeout_env.startswith("OPENAI_"):
        candidates.append(timeout_env.replace("OPENAI_", "GEMINI_", 1))
    elif timeout_env.startswith("GEMINI_"):
        candidates.append(timeout_env.replace("GEMINI_", "OPENAI_", 1))
    candidates.extend(["GEMINI_TIMEOUT", "OPENAI_TIMEOUT"])

    raw = None
    for name in candidates:
        value = os.getenv(name)
        if value not in (None, ""):
            raw = value
            break
    if raw is None:
        raw = str(default_timeout)
    try:
        return int(raw)
    except Exception:
        return default_timeout


def _get_gemini_key() -> Optional[str]:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _get_gemini_models() -> list[str]:
    primary = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    fallback = os.getenv("GEMINI_FALLBACK_MODEL", DEFAULT_GEMINI_FALLBACK_MODEL).strip() or DEFAULT_GEMINI_FALLBACK_MODEL
    models: list[str] = []
    for model in [primary, fallback, DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_FALLBACK_MODEL]:
        if model and model not in models:
            models.append(model)
    return models


def _extract_gemini_rest_text(body: dict) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = (((candidates[0].get("content") or {}).get("parts")) or [])
    texts = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(str(part["text"]))
    return "\n".join(texts).strip()


def _extract_gemini_sdk_text(response: Any) -> str:
    """Extract text from google-genai responses safely."""
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    # Some SDK versions expose candidates/parts instead of direct .text.
    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or []
            texts = []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    texts.append(str(part_text))
            if texts:
                return "\n".join(texts).strip()
    except Exception:
        pass

    return ""


def _build_gemini_config(
    *,
    system_prompt: Optional[str],
    json_mode: bool,
    temperature: float,
    max_output_tokens: int,
) -> Any:
    """Build config for current google-genai SDK, while tolerating SDK changes."""
    if types is None:
        return None

    data = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if json_mode:
        data["response_mime_type"] = "application/json"
    if system_prompt:
        data["system_instruction"] = system_prompt

    # New SDK accepts GenerateContentConfig. If fields differ in a future SDK,
    # progressively remove optional fields instead of crashing the whole app.
    for candidate in [data, {k: v for k, v in data.items() if k != "system_instruction"}, {"temperature": temperature, "max_output_tokens": max_output_tokens}]:
        try:
            return types.GenerateContentConfig(**candidate)
        except Exception:
            continue
    return None


def _call_gemini_sdk(
    *,
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: Optional[str],
    json_mode: bool,
    timeout: int,
    temperature: float,
    max_output_tokens: int,
) -> str:
    if genai is None:
        raise RuntimeError("google-genai package is not installed. Rebuild Docker after requirements.txt update.")

    # Make both env names available because the SDK can read GOOGLE_API_KEY by default.
    os.environ.setdefault("GOOGLE_API_KEY", api_key)

    http_options = None
    if types is not None:
        try:
            # v1 is preferred for stable models. If the SDK changes this field,
            # client creation below will fall back automatically.
            http_options = types.HttpOptions(api_version=os.getenv("GEMINI_API_VERSION", "v1"), timeout=timeout * 1000)
        except Exception:
            try:
                http_options = types.HttpOptions(api_version=os.getenv("GEMINI_API_VERSION", "v1"))
            except Exception:
                http_options = None

    try:
        client = genai.Client(api_key=api_key, http_options=http_options) if http_options else genai.Client(api_key=api_key)
    except TypeError:
        client = genai.Client(api_key=api_key)

    config = _build_gemini_config(
        system_prompt=system_prompt,
        json_mode=json_mode,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    try:
        if config is not None:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
        else:
            # If the SDK config schema changes, still allow basic generation.
            contents = prompt if not system_prompt else f"System instruction:\n{system_prompt}\n\nUser request:\n{prompt}"
            response = client.models.generate_content(model=model, contents=contents)
        text = _extract_gemini_sdk_text(response)
        if not text:
            raise RuntimeError(f"Gemini SDK returned no text. Raw response preview: {str(response)[:800]}")
        return text
    finally:
        try:
            client.close()
        except Exception:
            pass


def _call_gemini_rest(
    *,
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: Optional[str],
    json_mode: bool,
    timeout: int,
    temperature: float,
    max_output_tokens: int,
) -> str:
    # REST fallback uses the official generateContent endpoint and x-goog-api-key.
    api_version = os.getenv("GEMINI_REST_API_VERSION", "v1beta")
    url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    response = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini REST call failed for model {model}: HTTP {response.status_code}: {response.text[:1200]}")

    body = response.json()
    text = _extract_gemini_rest_text(body)
    if not text:
        raise RuntimeError(f"Gemini REST returned no text for model {model}. Raw body preview: {str(body)[:800]}")
    return text


def _call_gemini(
    *,
    prompt: str,
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    timeout_env: str = "GEMINI_TIMEOUT",
    default_timeout: int = 120,
    temperature: float = 0.05,
    max_output_tokens: int = 4096,
) -> Optional[str]:
    api_key = _get_gemini_key()
    if not api_key:
        return None

    timeout = _env_timeout(timeout_env, default_timeout)
    errors: list[str] = []
    use_sdk = (os.getenv("GEMINI_USE_SDK", "true").lower() not in {"0", "false", "no"})

    for model in _get_gemini_models():
        if use_sdk:
            try:
                return _call_gemini_sdk(
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    json_mode=json_mode,
                    timeout=timeout,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                errors.append(f"SDK {model}: {exc}")

        try:
            return _call_gemini_rest(
                api_key=api_key,
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=json_mode,
                timeout=timeout,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        except Exception as exc:
            errors.append(f"REST {model}: {exc}")

    raise RuntimeError("Gemini API call failed. Tried models: " + ", ".join(_get_gemini_models()) + ". Errors: " + " | ".join(errors[-6:]))


def _extract_openai_chat_text(body: dict) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("text"):
                    parts.append(str(item.get("text")))
                elif item.get("type") == "text" and item.get("content"):
                    parts.append(str(item.get("content")))
        return "\n".join(parts).strip()
    return ""


def _call_openai_chat(
    *,
    prompt: str,
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    timeout_env: str = "OPENAI_TIMEOUT",
    default_timeout: int = 120,
    temperature: float = 0.05,
    max_output_tokens: int = 4096,
) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    timeout = _env_timeout(timeout_env, default_timeout)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if json_mode:
        messages.append({"role": "system", "content": "Return ONLY valid JSON. Do not wrap it in markdown."})
    messages.append({"role": "user", "content": prompt})

    base_payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_output_tokens,
    }
    if json_mode:
        base_payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload_variants = [dict(base_payload)]
    p2 = dict(base_payload)
    p2["max_completion_tokens"] = p2.pop("max_tokens")
    payload_variants.append(p2)
    p3 = dict(p2)
    p3.pop("response_format", None)
    payload_variants.append(p3)
    p4 = dict(p3)
    p4.pop("temperature", None)
    payload_variants.append(p4)

    last_error = None
    for payload in payload_variants:
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}: {response.text}"
                if response.status_code == 400:
                    continue
                response.raise_for_status()
            body = response.json()
            text = _extract_openai_chat_text(body)
            if text:
                return text
            last_error = f"OpenAI returned no assistant text. Raw body preview: {str(body)[:800]}"
            continue
        except Exception as exc:
            last_error = str(exc)
            continue

    raise RuntimeError(f"OpenAI API call failed: {last_error}")


def ai_generate_text(
    *,
    prompt: str,
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    timeout_env: str = "GEMINI_TIMEOUT",
    default_timeout: int = 120,
    temperature: float = 0.05,
    max_output_tokens: int = 4096,
) -> Optional[str]:
    """Generate text using the configured provider.

    AI_PROVIDER=gemini is the default and uses GEMINI_API_KEY / GOOGLE_API_KEY.
    AI_PROVIDER=openai is still supported as an optional paid provider.
    """
    provider = (os.getenv("AI_PROVIDER") or "gemini").strip().lower()

    if provider in {"gemini", "google"}:
        return _call_gemini(
            prompt=prompt,
            system_prompt=system_prompt,
            json_mode=json_mode,
            timeout_env=timeout_env,
            default_timeout=default_timeout,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    if provider in {"openai", "chatgpt", "gpt"}:
        return _call_openai_chat(
            prompt=prompt,
            system_prompt=system_prompt,
            json_mode=json_mode,
            timeout_env=timeout_env,
            default_timeout=default_timeout,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    raise ValueError(f"Unsupported AI_PROVIDER: {provider}")


# Backward-compatible aliases for older project files.
gemini_generate_text = ai_generate_text
openai_generate_text = ai_generate_text
