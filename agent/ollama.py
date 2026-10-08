"""The local model, reached through Ollama's HTTP API. Standard library only.

Settings come from the environment so nothing is hard-wired:
    CARETAKER_MODEL     default qwen2.5:3b
    OLLAMA_URL          default http://127.0.0.1:11434
    CARETAKER_TIMEOUT   seconds to wait for one answer, default 45 (a laptop without a graphics card is slow)
"""
import json
import os
import time
import urllib.request

MODEL = os.environ.get("CARETAKER_MODEL", "qwen2.5:3b")
URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
TIMEOUT_S = float(os.environ.get("CARETAKER_TIMEOUT", "45"))

_cache = {"at": 0.0, "value": None}


def status(max_age=5.0):
    """{"model", "ready", "detail"}. Cached for a few seconds so the screen can poll it."""
    now = time.time()
    if _cache["value"] is not None and now - _cache["at"] < max_age:
        return _cache["value"]
    try:
        with urllib.request.urlopen(URL + "/api/tags", timeout=0.6) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
        if any(n == MODEL or n.split(":")[0] == MODEL or n.startswith(MODEL) for n in names):
            v = {"model": MODEL, "ready": True, "detail": "Model ready"}
        else:
            v = {"model": MODEL, "ready": False,
                 "detail": "Ollama is running but %s is not installed. Run: ollama pull %s" % (MODEL, MODEL)}
    except Exception:
        v = {"model": MODEL, "ready": False, "detail": "Model not running. Start Ollama to use it."}
    _cache.update(at=now, value=v)
    return v


def chat(system, user, schema=None, timeout=None):
    """One question, one answer. Returns the text, or None on any failure or timeout."""
    timeout = timeout or TIMEOUT_S
    body = {"model": MODEL, "stream": False, "keep_alive": "30m", "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if schema is not None:
        body["format"] = schema
    try:
        req = urllib.request.Request(URL + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("message", {}).get("content")
    except Exception:
        return None


def warm_up():
    """Load the model into memory so the first real answer is not slow. Safe to call when Ollama is off."""
    if status(max_age=0)["ready"]:
        chat("Reply with the single word ok.", "ok", timeout=60)
