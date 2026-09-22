"""Talking to an AI provider.

Free options first. Most services (Gemini, Groq, local Ollama) speak the
OpenAI chat format, so one adapter covers them; Anthropic gets its own.
Only the standard library is used, so there is nothing extra to install.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .store import ValidationError

PRESETS = {
    "none": {
        "label": "Basic mode (no AI)",
        "help": "Built-in rules only: capture, plan my day or week, overdue, search, move unfinished.",
        "needs_key": False, "format": None, "base_url": "", "model": "", "key_url": "",
    },
    "gemini": {
        "label": "Google Gemini (free tier)",
        "help": "Free key from Google AI Studio, no credit card. Free-tier prompts may be used by "
                "Google to improve its products.",
        "needs_key": True, "format": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash", "key_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq (free tier)",
        "help": "Free key, no credit card. Very fast, but the free per-minute token allowance is "
                "small, so long requests can be throttled.",
        "needs_key": True, "format": "openai", "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile", "key_url": "https://console.groq.com/keys",
    },
    "ollama": {
        "label": "Ollama (free, runs on your computer)",
        "help": "No key and no internet needed. Install Ollama, then run: ollama pull llama3.1",
        "needs_key": False, "format": "openai", "base_url": "http://127.0.0.1:11434/v1",
        "model": "llama3.1", "key_url": "https://ollama.com/download",
    },
    "openai_compatible": {
        "label": "Other OpenAI-compatible API",
        "help": "Any service with a /chat/completions endpoint that supports tool calling "
                "(OpenRouter, LM Studio, and so on).",
        "needs_key": False, "format": "openai", "base_url": "", "model": "", "key_url": "",
    },
    "anthropic": {
        "label": "Anthropic Claude (paid)",
        "help": "Best results; needs a paid API key.",
        "needs_key": True, "format": "anthropic", "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-5", "key_url": "https://console.anthropic.com/",
    },
}

FIELDS = ("provider", "api_key", "model", "base_url")


def save_config(store, provider, api_key=None, model=None, base_url=None):
    """Store the choice made on the Settings page."""
    if provider not in PRESETS:
        raise ValidationError(f'Unknown provider "{provider}"')
    current = {f: store.get_settings().get(f"ai.{f}", "") for f in FIELDS}
    model = (model or "").strip()[:300]
    base_url = (base_url or "").strip()[:300]
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ValidationError("The service URL must start with http:// or https://")
    key = (api_key or "").strip()
    if len(key) > 500:
        raise ValidationError("That API key is too long")
    # Keep a saved key only for the same provider at the same address, so a
    # changed URL can never inherit a key that was meant for somewhere else.
    same_target = current["provider"] == provider and current["base_url"] == base_url
    values = {"provider": provider, "api_key": key or (current["api_key"] if same_target else ""),
              "model": model, "base_url": base_url}
    for f in FIELDS:
        store.set_setting(f"ai.{f}", values[f])
    return resolve_config(store)


def resolve_config(store, env=None):
    """Environment variables win over the saved settings."""
    env = os.environ if env is None else env
    source = "app"
    settings = store.get_settings()
    raw = {f: settings.get(f"ai.{f}", "") for f in FIELDS}
    if env.get("AI_PROVIDER"):
        source = "env"
        raw = {"provider": env.get("AI_PROVIDER", ""), "api_key": env.get("AI_API_KEY", ""),
               "model": env.get("AI_MODEL", ""), "base_url": env.get("AI_BASE_URL", "")}
    elif env.get("ANTHROPIC_API_KEY"):
        source = "env"
        raw = {"provider": "anthropic", "api_key": env["ANTHROPIC_API_KEY"],
               "model": env.get("ANTHROPIC_MODEL", ""), "base_url": ""}

    provider = raw["provider"] if raw.get("provider") in PRESETS else "none"
    preset = PRESETS[provider]
    cfg = {
        "provider": provider, "label": preset["label"], "format": preset["format"],
        "api_key": raw.get("api_key") or "",
        "model": raw.get("model") or preset["model"],
        "base_url": (raw.get("base_url") or preset["base_url"]).rstrip("/"),
        "source": source, "help": preset["help"], "key_url": preset["key_url"],
        "needs_key": preset["needs_key"],
    }
    if provider == "none":
        cfg["problem"] = None
    elif preset["needs_key"] and not cfg["api_key"]:
        cfg["problem"] = "Add an API key to turn the AI on."
    elif not cfg["base_url"]:
        cfg["problem"] = "Add the service URL."
    elif not cfg["model"]:
        cfg["problem"] = "Add a model name."
    else:
        cfg["problem"] = None
    cfg["enabled"] = provider != "none" and not cfg["problem"]
    cfg["key_hint"] = f"…{cfg['api_key'][-4:]}" if cfg["api_key"] else ""
    return cfg


# ------------------------------------------------------------------ format
def to_openai_request(body, model):
    """Internal block format -> OpenAI chat format."""
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": body["system"]})
    for m in body["messages"]:
        content = m["content"]
        if isinstance(content, str):
            messages.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "\n".join(b["text"] for b in content if b["type"] == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                     for b in content if b["type"] == "tool_use"]
            msg = {"role": "assistant", "content": text or (None if calls else "")}
            if calls:
                msg["tool_calls"] = calls
            messages.append(msg)
        else:
            for b in content:
                if b["type"] == "tool_result":
                    payload = b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])
                    messages.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                                     "content": f"Error: {payload}" if b.get("is_error") else payload})
            text = "\n".join(b["text"] for b in content if b["type"] == "text")
            if text:
                messages.append({"role": "user", "content": text})
    req = {"model": model, "max_tokens": body.get("max_tokens", 2048), "messages": messages}
    if body.get("tools"):
        req["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in body["tools"]]
    return req


def from_openai_response(data):
    """OpenAI chat format -> internal block format."""
    choices = data.get("choices") or []
    if not choices:
        raise ValidationError("The AI service returned an empty response")
    msg = choices[0].get("message") or {}
    content = []
    raw = msg.get("content")
    text = raw if isinstance(raw, str) else "".join(p.get("text", "") for p in (raw or []))
    # Some local models wrap private reasoning in <think> tags.
    import re
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    if text:
        content.append({"type": "text", "text": text})
    for i, call in enumerate(msg.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        try:
            parsed = json.loads(args) if isinstance(args, str) and args.strip() else (args or {})
            if not isinstance(parsed, dict):
                raise ValueError
        except Exception:
            parsed = {"_invalid_arguments": str(args)[:500]}
        content.append({"type": "tool_use", "id": call.get("id") or f"call_{i}",
                        "name": fn.get("name"), "input": parsed})
    stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
    return {"content": content, "stop_reason": stop}


class AIUnavailable(Exception):
    """The provider couldn't be reached or refused the request."""


# ------------------------------------------------------------------ http
def _post(url, headers, payload, label, retries=2, timeout=90, opener=None, max_wait=6.0):
    data = json.dumps(payload).encode()
    waited = 0.0
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"content-type": "application/json", **headers})
        try:
            send = opener or urllib.request.urlopen
            with send(req, timeout=timeout) as res:
                return json.loads(res.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode() or "{}")
            except Exception:
                body = {}
            if isinstance(body, list):
                body = body[0] if body else {}
            detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) \
                else body.get("error") or f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                wait = min(2.0 ** attempt, 5.0)
                if waited + wait <= max_wait:
                    waited += wait
                    attempt += 1
                    time.sleep(wait)
                    continue
            if e.code in (401, 403):
                raise AIUnavailable(f"{label} rejected the API key ({detail})")
            if e.code == 429:
                raise AIUnavailable(f"{label} free-tier limit reached. Wait a minute and try again. ({detail})")
            if e.code == 404:
                raise AIUnavailable(f"{label} doesn't recognise the model or URL ({detail})")
            raise AIUnavailable(f"{label} error: {detail}")
        except urllib.error.URLError as e:
            raise AIUnavailable(f"Can't reach {label}. Is it running and is the URL right? ({e.reason})")
        except TimeoutError:
            raise AIUnavailable(f"{label} took too long to answer")


def make_caller(cfg, **opts):
    """Return call_model(body) for the agent loop, or None in basic mode."""
    if not cfg["enabled"]:
        return None
    label = cfg["label"].split(" (")[0]

    def call(body):
        if cfg["format"] == "anthropic":
            payload = {**body, "model": cfg["model"]}
            return _post(f"{cfg['base_url']}/messages",
                         {"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"},
                         payload, label, **opts)
        headers = {"authorization": f"Bearer {cfg['api_key']}"} if cfg["api_key"] else {}
        data = _post(f"{cfg['base_url']}/chat/completions", headers,
                     to_openai_request(body, cfg["model"]), label, **opts)
        return from_openai_response(data)

    return call


def test_connection(cfg, **opts):
    """Used by the Test button on the Settings page."""
    if cfg["provider"] == "none":
        return True, "Basic mode needs no connection."
    if not cfg["enabled"]:
        return False, cfg["problem"]
    call = make_caller(cfg, retries=0, **opts)
    started = time.time()
    try:
        res = call({"max_tokens": 50, "system": "Reply with the single word OK.",
                    "messages": [{"role": "user", "content": "Ping"}]})
        text = " ".join(b["text"] for b in res["content"] if b["type"] == "text").strip()
        ms = int((time.time() - started) * 1000)
        return True, f"Connected to {cfg['label']} ({cfg['model']}) in {ms} ms." + (f' Reply: "{text[:40]}"' if text else "")
    except Exception as e:
        return False, str(e)
