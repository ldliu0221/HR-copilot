import json
import os
import re
import traceback
import urllib.request

from app.config.service import active_model_config, load_app_config
from app.core.storage import now_iso

def call_llm_json(system_prompt, user_payload, temperature=0.2, timeout=25, cap_timeout=False):
    config = load_app_config()
    if not config.get("llm_enabled"):
        return {"error": "llm_disabled"}
    model_cfg = active_model_config(config)
    api_key = get_llm_api_key(config, model_cfg)
    payload = {
        "model": model_cfg.get("model") or config.get("llm_model", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_prompt + " 只输出 JSON，不要输出 Markdown。"},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": float(model_cfg.get("temperature", temperature) or temperature),
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(normalize_llm_endpoint(model_cfg.get("base_url") or config.get("llm_base_url")), data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        request_timeout = int(model_cfg.get("timeout", timeout) or timeout)
        if cap_timeout:
            request_timeout = min(request_timeout, timeout)
        with urllib.request.urlopen(req, timeout=request_timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0) if match else content)
    except Exception as exc:
        return {"error": str(exc)}


def get_llm_api_key(config, model_cfg=None):
    model_cfg = model_cfg or active_model_config(config)
    return model_cfg.get("api_key") or config.get("llm_api_key") or os.environ.get(model_cfg.get("api_key_env") or config.get("llm_api_key_env", "OPENAI_API_KEY"), "")


def normalize_llm_endpoint(base_url):
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return "https://api.openai.com/v1/chat/completions"
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url


def normalize_models_endpoint(base_url):
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return "https://api.openai.com/v1/models"
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    if url.endswith("/v1"):
        return url + "/models"
    return url + "/models"


def test_model_config(model):
    api_key = model.get("api_key") or os.environ.get(model.get("api_key_env") or "OPENAI_API_KEY", "")
    payload = {
        "model": model.get("model", ""),
        "messages": [
            {"role": "system", "content": "????????????? JSON?"},
            {"role": "user", "content": "{\"task\":\"ping\"}"},
        ],
        "temperature": float(model.get("temperature", 0.2) or 0.2),
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        normalize_llm_endpoint(model.get("base_url")),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=min(int(model.get("timeout", 30) or 30), 30)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        available_models = []
        models_error = ""
        try:
            models_req = urllib.request.Request(normalize_models_endpoint(model.get("base_url")), headers=headers, method="GET")
            with urllib.request.urlopen(models_req, timeout=10) as resp:
                models_data = json.loads(resp.read().decode("utf-8"))
            available_models = [
                item.get("id") or item.get("model") or item.get("name")
                for item in models_data.get("data", [])
                if isinstance(item, dict)
            ]
        except Exception as exc:
            models_error = str(exc)
        target = model.get("model", "")
        model_found = (not available_models) or target in available_models
        message = "API ???" + ("?????" if model_found else "?????????")
        return {
            "ok": True,
            "status": "??",
            "message": message,
            "raw_message": content[:180],
            "available_models": available_models[:20],
            "models_error": models_error,
            "model_found": model_found,
            "time": now_iso(),
        }
    except Exception as exc:
        return {"ok": False, "status": "??", "message": str(exc), "time": now_iso()}


