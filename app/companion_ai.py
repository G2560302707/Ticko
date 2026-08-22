# -*- coding: utf-8 -*-
"""Ticko 智能伙伴：角色卡、最小化上下文和兼容 OpenAI / Ollama 的对话客户端。"""

import json
import re
import urllib.error
import urllib.request
import companion_templates


PROVIDERS = ("off", "openai", "ollama")
PERSONAS = ("gentle", "coach", "cheerful", "calm")
ACTIONS = ("hello", "walk", "celebrate", "rest", "home")
MAX_HISTORY = 12
MAX_MESSAGE = 480
MAX_REPLY = 96
INTERACTION_LEVELS = ("light", "medium", "heavy")
LEVEL_POLICIES = {
    "light": {"history": 2, "max_tokens": 56, "daily_requests": 60, "auto_events": 0, "cooldown": 1800},
    "medium": {"history": 5, "max_tokens": 88, "daily_requests": 140, "auto_events": 8, "cooldown": 720},
    "heavy": {"history": 8, "max_tokens": 128, "daily_requests": 280, "auto_events": 24, "cooldown": 180},
}

PERSONA_TEXT = {
    "gentle": "温柔、细腻，简短关心用户，但不说教。",
    "coach": "清晰、有行动感，给出一个小而具体的下一步。",
    "cheerful": "明快、有活力，适度庆祝每一点进展。",
    "calm": "安静、克制，像可靠的专注搭子。",
}


def normalize_provider(value):
    return value if value in PROVIDERS else "off"


def normalize_persona(value):
    return value if value in PERSONAS else "gentle"


def normalize_interaction_level(value):
    return value if value in INTERACTION_LEVELS else "medium"


def level_policy(value):
    return dict(LEVEL_POLICIES[normalize_interaction_level(value)])


def clean_text(value, limit):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def public_settings(meta_get):
    provider = normalize_provider(meta_get("ai_provider") or "off")
    return {
        "enabled": (meta_get("ai_enabled") or "0") == "1",
        "provider": provider,
        "base_url": meta_get("ai_base_url") or default_base_url(provider),
        "model": meta_get("ai_model") or default_model(provider),
        "api_key_configured": bool(meta_get("ai_api_key") or ""),
        "share_app": (meta_get("ai_share_app") or "0") == "1",
        "name": clean_text(meta_get("ai_name") or "Ticko", 28) or "Ticko",
        "persona": normalize_persona(meta_get("ai_persona") or "gentle"),
        "custom_prompt": clean_text(meta_get("ai_custom_prompt") or "", 320),
        "interaction_level": normalize_interaction_level(meta_get("ai_interaction_level") or "medium"),
    }


def default_base_url(provider):
    if provider == "ollama":
        return "http://127.0.0.1:11434"
    if provider == "openai":
        return "https://api.openai.com/v1"
    return ""


def default_model(provider):
    if provider == "ollama":
        return "qwen3:4b"
    if provider == "openai":
        return "gpt-4o-mini"
    return ""


def validate_config(data, existing):
    """返回可持久化的非机密配置。密钥独立处理，避免被接口回显。"""
    data = data or {}
    provider = normalize_provider(data.get("ai_provider", existing["provider"]))
    base_url = clean_text(data.get("ai_base_url", existing["base_url"]), 300).rstrip("/")
    if provider != "off" and not re.match(r"^https?://[^\s/]+", base_url, re.I):
        base_url = default_base_url(provider)
    model = clean_text(data.get("ai_model", existing["model"]), 120) or default_model(provider)
    return {
        "enabled": bool(data.get("ai_enabled", existing["enabled"])),
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "share_app": bool(data.get("ai_share_app", existing["share_app"])),
        "name": clean_text(data.get("ai_name", existing["name"]), 28) or "Ticko",
        "persona": normalize_persona(data.get("ai_persona", existing["persona"])),
        "custom_prompt": clean_text(data.get("ai_custom_prompt", existing["custom_prompt"]), 320),
        "interaction_level": normalize_interaction_level(data.get("ai_interaction_level", existing.get("interaction_level", "medium"))),
    }


def context_from_snapshot(snapshot, share_app=False):
    snap = snapshot or {}
    context = {
        "伙伴状态": snap.get("label") or "陪伴中",
        "有效使用秒数": int(snap.get("active_seconds") or 0),
        "专注占比": round(float(snap.get("focus_ratio") or 0), 1),
        "应用切换次数": int(snap.get("switches") or 0),
        "番茄钟": (snap.get("pomodoro") or {}).get("mode") or "idle",
    }
    if share_app and snap.get("current_app"):
        context["当前应用"] = clean_text(snap["current_app"], 80)
    return context


def fallback_reply(snapshot, message, persona, templates=None):
    text = clean_text(message, MAX_MESSAGE)
    template_reply, scene = companion_templates.reply(snapshot, text, templates or [])
    state = (snapshot or {}).get("state") or "companion"
    active = int((snapshot or {}).get("active_seconds") or 0)
    actions = {"summary": "rest", "celebrate": "celebrate", "focus": "rest", "break": "rest", "switch": "rest", "away": "hello", "next": "hello", "encourage": "hello"}
    return template_reply, actions.get(scene, "hello")


def _system_prompt(settings, snapshot):
    profile = settings["name"] + "，是 Ticko 的时间伙伴。"
    return "\n".join((
        profile,
        "性格：" + PERSONA_TEXT[settings["persona"]],
        "请只用简体中文回答，语气自然，优先一句话，最多两句、60字以内。",
        "不要假装看见未提供的数据；不要评价隐私；不要给医疗、法律或财务建议。",
        "只依据以下匿名统计摘要，不含窗口标题：" + json.dumps(context_from_snapshot(snapshot, settings["share_app"]), ensure_ascii=False),
        "如适合动作，在最后另起一行输出 [action:hello|walk|celebrate|rest|home]，否则不输出动作。",
        ("补充角色设定：" + settings["custom_prompt"]) if settings["custom_prompt"] else "",
    ))


def _request_json(url, payload, headers, timeout=12):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            raw = exc.read().decode("utf-8", "ignore")
            parsed = json.loads(raw)
            err = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(err, dict):
                detail = clean_text(err.get("message") or err.get("code"), 180)
            elif isinstance(err, str):
                detail = clean_text(err, 180)
        except Exception:
            pass
        message = "服务返回 %s" % exc.code
        return None, message + ("：" + detail if detail else "")
    except urllib.error.URLError:
        return None, "无法连接模型服务"
    except Exception:
        return None, "模型响应异常"


def _extract_reply(text, default_action):
    text = clean_text(text, MAX_REPLY)
    action = default_action
    match = re.search(r"\[action:(hello|walk|celebrate|rest|home)\]", text, re.I)
    if match:
        action = match.group(1).lower()
        text = text[:match.start()].strip()
    return text or "我在这里。", action


def _response_error(data):
    """提取兼容接口在 2xx 响应中返回的错误，便于用户定位配置问题。"""
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        return clean_text(error.get("message") or error.get("code") or error.get("type"), 180)
    if isinstance(error, str):
        return clean_text(error, 180)
    return clean_text(data.get("message") or data.get("detail"), 180)


def _is_deepseek(settings):
    """识别 DeepSeek 的 OpenAI 兼容端点，不影响其它服务商。"""
    base_url = (settings.get("base_url") or "").lower()
    model = (settings.get("model") or "").lower()
    return "deepseek" in base_url or model.startswith("deepseek-")


def generate(settings, snapshot, message, history, recommendation="hello", templates=None):
    """生成回复。失败必定降级到本地文案，不让桌宠失去回应。"""
    message = clean_text(message, MAX_MESSAGE)
    local, local_action = fallback_reply(snapshot, message, settings["persona"], templates)
    if not settings["enabled"] or settings["provider"] == "off":
        return {"reply": local, "action": local_action, "source": "local", "error": ""}
    policy = level_policy(settings.get("interaction_level"))
    messages = [{"role": "system", "content": _system_prompt(settings, snapshot)}]
    for item in (history or [])[-policy["history"]:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = clean_text(item.get("content"), MAX_REPLY)
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message or "请根据现在的时间数据，给我一句简短陪伴。"})
    if settings["provider"] == "ollama":
        data, error = _request_json(settings["base_url"] + "/api/chat", {"model": settings["model"], "messages": messages, "stream": False, "options": {"num_predict": policy["max_tokens"]}}, {"Content-Type": "application/json"})
        content = ((data or {}).get("message") or {}).get("content") if data else ""
    else:
        headers = {"Content-Type": "application/json"}
        api_key = settings.get("api_key") or ""
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        payload = {"model": settings["model"], "messages": messages, "temperature": 0.7, "max_tokens": policy["max_tokens"]}
        # 桌宠只需一两句自然回应；关闭 DeepSeek V4 的思考链，避免占满短回复额度。
        if _is_deepseek(settings):
            payload["thinking"] = {"type": "disabled"}
        data, error = _request_json(settings["base_url"] + "/chat/completions", payload, headers)
        choices = (data or {}).get("choices") or []
        content = ((choices[0].get("message") or {}).get("content")) if choices else ""
    if not content:
        return {"reply": local, "action": local_action, "source": "local", "error": error or _response_error(data) or "模型没有返回内容"}
    reply, action = _extract_reply(content, recommendation or local_action)
    return {"reply": reply, "action": action, "source": "model", "error": ""}


def test_connection(settings):
    if not settings["enabled"] or settings["provider"] == "off":
        return False, "请先启用并选择模型服务。"
    probe = generate(settings, {"active_seconds": 0, "focus_ratio": 0, "switches": 0, "pomodoro": {}}, "请回复：连接正常", [], "hello")
    if probe["source"] != "model":
        return False, probe["error"] or "连接未成功"
    return True, "连接正常"
