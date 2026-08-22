# -*- coding: utf-8 -*-
"""进程名 + 窗口标题启发式分类。"""
import copy
import json
import re

from classify_words import (
    EXCLUDE_LEARN,
    EXTRA_EXE,
    FUN_SITES,
    FUN_TITLE,
    LEARN_SITES,
    LEARN_WORDS,
    SOCIAL_SITES,
    SOCIAL_TITLE,
    WORK_SITES,
    WORK_TITLE,
)

CATEGORIES = ("学习", "娱乐", "工作", "社交", "系统", "其他")
CLASSIFY_REV = "4"

# 浏览器默认算娱乐；教育站点 / 标题关键词可以改成学习、工作、社交。
BROWSERS = frozenset({
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
    "chromium.exe",
    "iexplore.exe",
    "360chrome.exe",
    "360se.exe",
    "qqbrowser.exe",
    "sogouexplorer.exe",
    "2345explorer.exe",
    "liebao.exe",
})

SKIP_EXE = frozenset({
    "applicationframehost.exe",
})

FUN_EXES = frozenset({
    "bilibili.exe",
    "spotify.exe",
    "cloudmusic.exe",
    "qqmusic.exe",
    "kugou.exe",
    "kwmusic.exe",
})


def _site_entry(needles, default):
    return {"needles": list(needles), "default": default}


BUILTIN_SITES = [
    _site_entry(LEARN_SITES, "学习"),
    _site_entry(WORK_SITES, "工作"),
    _site_entry(SOCIAL_SITES, "社交"),
    _site_entry(FUN_SITES, "娱乐"),
]

DEFAULT_EXE = {
    "code.exe": "工作",
    "cursor.exe": "工作",
    "devenv.exe": "工作",
    "idea64.exe": "工作",
    "pycharm64.exe": "工作",
    "winword.exe": "工作",
    "excel.exe": "工作",
    "powerpnt.exe": "工作",
    "wps.exe": "工作",
    "notepad.exe": "工作",
    "notepad++.exe": "工作",
    "weixin.exe": "社交",
    "wechat.exe": "社交",
    "qq.exe": "社交",
    "telegram.exe": "社交",
    "discord.exe": "社交",
    "steam.exe": "娱乐",
    "steamwebhelper.exe": "娱乐",
    "potplayer.exe": "娱乐",
    "potplayer64.exe": "娱乐",
    "vlc.exe": "娱乐",
    "mpv.exe": "娱乐",
    "yuanshen.exe": "娱乐",
    "genshinimpact.exe": "娱乐",
    "starrail.exe": "娱乐",
    "leagueclient.exe": "娱乐",
    "league of legends.exe": "娱乐",
    "lockapp.exe": "系统",
    "explorer.exe": "系统",
    "searchhost.exe": "系统",
    "ticko.exe": "系统",
}
DEFAULT_EXE.update(EXTRA_EXE)

DEFAULT_RULES = {
    "exe": dict(DEFAULT_EXE),
    "sites": copy.deepcopy(BUILTIN_SITES),
    "learn_words": list(LEARN_WORDS),
    "exclude_learn": list(EXCLUDE_LEARN),
}


def _compile_needles(words):
    parts = [re.escape(w) for w in words if w]
    if not parts:
        return None
    parts.sort(key=len, reverse=True)
    return re.compile("|".join(parts), re.IGNORECASE)


_LEARN_RE = _compile_needles(LEARN_WORDS)
_EXCLUDE_RE = _compile_needles(EXCLUDE_LEARN)


def _clean_words(seq):
    out = []
    seen = set()
    for w in seq or []:
        if not isinstance(w, str):
            continue
        w = w.strip()
        if not w or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def _clean_sites(seq):
    cleaned = []
    for s in seq or []:
        if not isinstance(s, dict):
            continue
        needles = _clean_words(s.get("needles") or [])
        default = s.get("default") if s.get("default") in CATEGORIES else "娱乐"
        if needles:
            cleaned.append({"needles": needles, "default": default})
    return cleaned


def _site_key(site):
    return (site.get("default"), tuple(n.lower() for n in site.get("needles") or []))


_BUILTIN_SITE_KEYS = {_site_key(s) for s in BUILTIN_SITES}
_BUILTIN_LEARN = {w.lower() for w in LEARN_WORDS}
_BUILTIN_EXCLUDE = {w.lower() for w in EXCLUDE_LEARN}


def editor_rules(raw):
    """给设置页用的精简 JSON：内置词库不塞进文本框。"""
    user = _user_overlay(raw if isinstance(raw, dict) else {})
    return {
        "exe": dict(user["exe"]),
        "sites": list(user["sites"]),
        "learn_words": list(user["learn_words"]),
        "exclude_learn": list(user["exclude_learn"]),
        "builtin": {
            "learn_words": len(LEARN_WORDS),
            "exclude_learn": len(EXCLUDE_LEARN),
            "sites": sum(len(s["needles"]) for s in BUILTIN_SITES),
        },
    }


def _user_overlay(raw):
    exe = {}
    if isinstance(raw.get("exe"), dict):
        for k, v in raw["exe"].items():
            if not isinstance(k, str) or v not in CATEGORIES:
                continue
            key = k.strip().lower()
            if DEFAULT_EXE.get(key) == v:
                continue
            exe[key] = v
    sites = []
    for s in _clean_sites(raw.get("sites")):
        if _site_key(s) in _BUILTIN_SITE_KEYS:
            continue
        sites.append(s)
    learn = [w for w in _clean_words(raw.get("learn_words")) if w.lower() not in _BUILTIN_LEARN]
    exclude = [w for w in _clean_words(raw.get("exclude_learn")) if w.lower() not in _BUILTIN_EXCLUDE]
    return {"exe": exe, "sites": sites, "learn_words": learn, "exclude_learn": exclude}


def normalize_rules(raw):
    overlay = _user_overlay(raw if isinstance(raw, dict) else {})
    exe = dict(DEFAULT_EXE)
    exe.update(overlay["exe"])
    sites = overlay["sites"] + copy.deepcopy(BUILTIN_SITES)
    learn = list(LEARN_WORDS) + overlay["learn_words"]
    exclude = list(EXCLUDE_LEARN) + overlay["exclude_learn"]
    return {
        "exe": exe,
        "sites": sites,
        "learn_words": learn,
        "exclude_learn": exclude,
    }


def load_rules_json(text):
    try:
        return normalize_rules(json.loads(text) if text else {})
    except Exception:
        return normalize_rules({})


def overlay_json(text):
    try:
        raw = json.loads(text) if text else {}
    except Exception:
        raw = {}
    return _user_overlay(raw if isinstance(raw, dict) else {})


def classify(app, title, rules=None):
    rules = normalize_rules(rules or {})
    exe = (app or "").strip().lower()
    text = title or ""
    site_cat = _site_category(text, rules)
    if site_cat:
        return site_cat
    if exe in FUN_EXES:
        if _has_learn(text, rules):
            return "学习"
        return rules.get("exe", {}).get(exe, "娱乐")
    if exe in rules.get("exe", {}) and exe not in SKIP_EXE:
        return rules["exe"][exe]
    if _has_any(text, WORK_TITLE):
        return "工作"
    if _has_any(text, SOCIAL_TITLE):
        return "社交"
    if _has_learn(text, rules):
        return "学习"
    if exe in BROWSERS or exe in SKIP_EXE:
        return "娱乐"
    if _has_any(text, FUN_TITLE):
        return "娱乐"
    return "其他"


def _site_category(text, rules):
    for site in rules.get("sites") or []:
        if not _has_any(text, site.get("needles") or []):
            continue
        default = site.get("default") or "娱乐"
        if default == "学习":
            return "学习"
        if default in ("娱乐",) and _has_learn(text, rules):
            return "学习"
        return default
    return None


def _has_learn(text, rules):
    if not text:
        return False
    extra_ex = [w for w in (rules.get("exclude_learn") or []) if w.lower() not in _BUILTIN_EXCLUDE]
    extra_learn = [w for w in (rules.get("learn_words") or []) if w.lower() not in _BUILTIN_LEARN]
    if _EXCLUDE_RE and _EXCLUDE_RE.search(text):
        return False
    if extra_ex and _has_any(text, extra_ex):
        return False
    if _LEARN_RE and _LEARN_RE.search(text):
        return True
    return _has_any(text, extra_learn)


def _has_any(text, needles):
    if not text or not needles:
        return False
    low = text.lower()
    for n in needles:
        if not n:
            continue
        if n.lower() in low or n in text:
            return True
    return False
