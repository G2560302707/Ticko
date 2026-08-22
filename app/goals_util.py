# -*- coding: utf-8 -*-
"""每日目标与忽略名单（纯本地，无网络）。"""
import json
import re

import classify as classify_mod

DEFAULT_IGNORE_APPS = ("ticko.exe", "explorer.exe", "lockapp.exe")
DEFAULT_IGNORE_MIN = 5.0
CATEGORIES = classify_mod.CATEGORIES
STEP_MINUTES = 5

_HM = re.compile(r"^(\d+):(\d{1,2})(?::(\d{1,2}))?$")
_H_M = re.compile(r"^(\d+(?:\.\d+)?)h(\d+(?:\.\d+)?)m?$")
_H_ONLY = re.compile(r"^(\d+(?:\.\d+)?)h$")
_M_ONLY = re.compile(r"^(\d+(?:\.\d+)?)m$")
_S_ONLY = re.compile(r"^(\d+(?:\.\d+)?)s$")


def parse_duration_text(value):
    """把用户输入转成秒。空串为 None。整数当分钟，1:30 / 1h30 / 1.5h 均可。"""
    if value is None or value is False:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = (
        text.replace("小时", "h")
        .replace("钟头", "h")
        .replace("时", "h")
        .replace("分钟", "m")
        .replace("分", "m")
        .replace("秒", "s")
    )
    text = re.sub(r"\s+", "", text).lower()
    m = _HM.match(text)
    if m:
        hours = int(m.group(1))
        mins = int(m.group(2))
        secs = int(m.group(3) or 0)
        if mins >= 60 or secs >= 60:
            return None
        return hours * 3600 + mins * 60 + secs
    m = _H_M.match(text)
    if m:
        return int(round(float(m.group(1)) * 3600 + float(m.group(2)) * 60))
    m = _H_ONLY.match(text)
    if m:
        return int(round(float(m.group(1)) * 3600))
    m = _M_ONLY.match(text)
    if m:
        return int(round(float(m.group(1)) * 60))
    m = _S_ONLY.match(text)
    if m:
        return int(round(float(m.group(1))))
    try:
        n = float(text)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    if "." in text:
        return int(round(n * 3600))
    return int(round(n)) * 60


def format_duration_short(sec):
    if sec is None or sec is False:
        return ""
    try:
        sec = int(round(float(sec)))
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    hours = sec // 3600
    mins = (sec % 3600) // 60
    if hours and mins:
        return "%d小时%d分" % (hours, mins)
    if hours:
        return "%d小时" % hours
    return "%d分" % mins


def step_duration(sec, delta_minutes, step_minutes=STEP_MINUTES):
    try:
        cur = 0 if sec is None else int(sec)
    except (TypeError, ValueError):
        cur = 0
    nxt = cur + int(delta_minutes) * 60
    if nxt < 0:
        nxt = 0
    return nxt


def round_to_step(sec, step=300):
    if sec is None:
        return None
    try:
        n = int(round(float(sec)))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return 0
    step = int(step) or 300
    return int(round(n / float(step)) * step)


def _as_int_seconds(value):
    if value is None or value is False:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return int(round(n))


def _pair(raw):
    if not isinstance(raw, dict):
        return {"min": None, "max": None}
    mn = _as_int_seconds(raw.get("min"))
    mx = _as_int_seconds(raw.get("max"))
    if mn is not None and mx is not None and mn > mx:
        mx = mn
    return {"min": mn, "max": mx}


def parse_exe_list(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                raw = data
            else:
                raw = [ln.strip() for ln in text.replace(",", "\n").splitlines()]
        except Exception:
            raw = [ln.strip() for ln in text.replace(",", "\n").splitlines()]
    if not isinstance(raw, (list, tuple)):
        return None
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        name = item.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def normalize_ignore_config(apps_raw=None, min_raw=None, apps_missing=True):
    parsed = parse_exe_list(apps_raw)
    if parsed is None or apps_missing:
        apps = list(DEFAULT_IGNORE_APPS)
    else:
        # Migrate the app's former runtime names without disturbing the user's
        # other ignore choices. Ticko must not record its own window.
        apps = ["ticko.exe" if item in ("pcusage.exe", "pythonw.exe") else item for item in parsed]
    try:
        if min_raw is None or min_raw == "":
            minimum = DEFAULT_IGNORE_MIN
        else:
            minimum = float(min_raw)
    except (TypeError, ValueError):
        minimum = DEFAULT_IGNORE_MIN
    if minimum < 0:
        minimum = 0.0
    if minimum > 120:
        minimum = 120.0
    return {"apps": apps, "min_seconds": minimum}


def should_credit_app(app, duration=None, cfg=None):
    cfg = cfg or normalize_ignore_config()
    name = (app or "").strip().lower()
    if not name:
        return False
    ignored = set(cfg.get("apps") or ())
    if name in ignored:
        return False
    if duration is not None:
        try:
            dur = float(duration)
        except (TypeError, ValueError):
            dur = 0.0
        if dur < float(cfg.get("min_seconds") or 0):
            return False
    return True


def normalize_daily_goals(raw=None):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    cats_raw = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
    categories = {}
    for name in CATEGORIES:
        categories[name] = _pair(cats_raw.get(name))
    return {"active": _pair(raw.get("active")), "categories": categories}


def _status_for(kind, current, target):
    if not target:
        return "ok", 0.0
    ratio = float(current) / float(target)
    if kind == "min":
        if current >= target:
            return "done", ratio
        if ratio >= 0.9:
            return "near", ratio
        return "ok", ratio
    if current > target:
        return "over", ratio
    if ratio >= 0.9:
        return "near", ratio
    return "ok", ratio


def _item(gid, label, kind, current, target):
    status, ratio = _status_for(kind, current, target)
    bar = min(1.0, ratio) if target else 0.0
    return {
        "id": gid,
        "label": label,
        "kind": kind,
        "target": int(target),
        "current": int(round(max(0.0, current))),
        "ratio": round(ratio, 4),
        "bar": round(bar, 4),
        "status": status,
    }


def goals_progress(active_seconds, category_seconds, goals=None):
    goals = normalize_daily_goals(goals)
    current_active = max(0.0, float(active_seconds or 0))
    cat_map = category_seconds or {}
    items = []
    spec = goals["active"]
    if spec["min"] is not None:
        items.append(_item("active-min", "活跃", "min", current_active, spec["min"]))
    if spec["max"] is not None:
        items.append(_item("active-max", "活跃", "max", current_active, spec["max"]))
    for name in CATEGORIES:
        pair = goals["categories"][name]
        cur = max(0.0, float(cat_map.get(name) or 0))
        if pair["min"] is not None:
            items.append(_item("cat-min-" + name, name, "min", cur, pair["min"]))
        if pair["max"] is not None:
            items.append(_item("cat-max-" + name, name, "max", cur, pair["max"]))
    return items
