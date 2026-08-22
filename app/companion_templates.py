# -*- coding: utf-8 -*-
"""Ticko 离线陪伴模板：本机存储、数据插值与场景选择。"""

import hashlib
import re
import uuid


SCENES = (
    ("greeting", "问候"), ("identity", "自我介绍"), ("summary", "今日总结"),
    ("encourage", "鼓励"), ("next", "下一步"), ("focus", "专注中"),
    ("break", "休息"), ("switch", "切换频繁"), ("celebrate", "目标完成"),
    ("away", "回来啦"),
)
SCENE_NAMES = dict(SCENES)
MAX_CUSTOM = 40
MAX_TEXT = 180

DEFAULTS = (
    ("greeting", "我在呢。今天已经投入 {{active_minutes}} 分钟，我们慢慢来。"),
    ("greeting", "嗨，Ticko 在。现在把注意力放回眼前这一件事就好。"),
    ("identity", "我是 Ticko，你的时间伙伴。今天我会陪你把节奏过得清楚一点。"),
    ("summary", "今天已有效投入 {{active_minutes}} 分钟，专注占比 {{focus_ratio}}%。"),
    ("summary", "到现在为止，你已经完成 {{active_minutes}} 分钟投入；接下来做最重要的一件事。"),
    ("encourage", "你已经走在节奏里了，先完成眼前这一小步。"),
    ("encourage", "不用赶，把下一件事做完，就已经很好。"),
    ("next", "现在最适合开始一个 5 分钟的小任务，要我陪你一起开始吗？"),
    ("next", "先选一件最重要的事，只做它的第一步。"),
    ("focus", "你正在专注。先别切换，给这件事再留一点时间。"),
    ("break", "辛苦了，短暂休息一下，回来后我们继续。"),
    ("switch", "今天已经切换 {{switches}} 次了。先关掉一个干扰，再继续当前任务。"),
    ("celebrate", "这个目标完成得很漂亮。今天的努力值得认真庆祝。"),
    ("celebrate", "完成啦。把这份成就感收好，再决定下一步。"),
    ("away", "欢迎回来。先花十秒想想，接下来最想完成什么？"),
)


def clean(value, limit=MAX_TEXT):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_item(raw):
    raw = raw or {}
    scene = str(raw.get("scene") or "encourage")
    if scene not in SCENE_NAMES:
        scene = "encourage"
    text = clean(raw.get("text"))
    if not text:
        return None
    return {
        "id": clean(raw.get("id"), 64) or uuid.uuid4().hex,
        "name": clean(raw.get("name"), 40) or SCENE_NAMES[scene],
        "scene": scene,
        "text": text,
        "enabled": bool(raw.get("enabled", True)),
    }


def normalize_custom(raw):
    items, ids = [], set()
    for value in raw if isinstance(raw, list) else []:
        item = normalize_item(value)
        if item and item["id"] not in ids:
            items.append(item)
            ids.add(item["id"])
        if len(items) >= MAX_CUSTOM:
            break
    return items


def public_items(custom):
    builtins = [{"id": "builtin-%02d" % i, "name": SCENE_NAMES[scene], "scene": scene, "text": text, "enabled": True, "builtin": True} for i, (scene, text) in enumerate(DEFAULTS, 1)]
    return {"scenes": [{"id": key, "name": value} for key, value in SCENES], "defaults": builtins, "custom": normalize_custom(custom)}


def context(snapshot):
    snap = snapshot or {}
    return {
        "active_minutes": max(0, int(snap.get("active_seconds") or 0) // 60),
        "focus_ratio": round(float(snap.get("focus_ratio") or 0), 1),
        "switches": max(0, int(snap.get("switches") or 0)),
        "state": str(snap.get("state") or "companion"),
    }


def choose_scene(snapshot, message):
    text = clean(message).lower()
    state = str((snapshot or {}).get("state") or "")
    if any(word in text for word in ("你是谁", "叫什么", "名字")):
        return "identity"
    if any(word in text for word in ("总结", "今天", "状态", "数据")):
        return "summary"
    if any(word in text for word in ("鼓励", "加油", "累", "不想")):
        return "encourage"
    if any(word in text for word in ("下一步", "做什么", "开始", "计划")):
        return "next"
    if state == "celebrate" or any(word in text for word in ("完成", "庆祝", "目标")):
        return "celebrate"
    if state == "focus":
        return "focus"
    if state == "away":
        return "away"
    if int((snapshot or {}).get("switches") or 0) >= 24:
        return "switch"
    if any(word in text for word in ("你好", "嗨", "在吗", "hello")):
        return "greeting"
    return "greeting"


def render(text, values):
    return re.sub(r"\{\{(active_minutes|focus_ratio|switches)\}\}", lambda m: str(values.get(m.group(1), "")), text)


def reply(snapshot, message, custom):
    scene = choose_scene(snapshot, message)
    all_items = [{"scene": item_scene, "text": item_text} for item_scene, item_text in DEFAULTS]
    all_items += [item for item in normalize_custom(custom) if item["enabled"]]
    matches = [item for item in all_items if item["scene"] == scene]
    if not matches:
        matches = [item for item in all_items if item["scene"] == "greeting"] or [{"text": "我在呢。"}]
    values = context(snapshot)
    seed = "%s:%s:%s" % (scene, values["active_minutes"], values["switches"])
    index = int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16) % len(matches)
    return render(matches[index]["text"], values), scene
