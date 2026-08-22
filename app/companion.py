# -*- coding: utf-8 -*-
"""Ticko 伙伴状态：把时间记录翻译成克制、可解释的桌宠行为。"""

import time

BEHAVIOR_MODES = ("companion", "focus", "quiet")
ACTION_NAMES = ("hello", "walk", "celebrate", "rest", "home")


def normalize_behavior(value):
    return value if value in BEHAVIOR_MODES else "companion"


def _goal_done(goals):
    return any(item.get("status") in ("done", "over") for item in (goals or ()))


def build_snapshot(dashboard, pomodoro, behavior="companion", now=None):
    """创建供面板和桌宠共用的轻量快照；不暴露原始窗口标题。"""
    dashboard = dashboard or {}
    today = dashboard.get("today") or {}
    clock = dashboard.get("clock") or {}
    pomodoro = pomodoro or {}
    behavior = normalize_behavior(behavior)
    now = time.time() if now is None else float(now)
    active = max(0, int(today.get("active") or 0))
    focus_ratio = max(0, min(100, float(dashboard.get("focus_ratio") or 0)))
    state = "companion"
    label = "陪伴中"
    message = "我在这里，陪你把今天过好。"
    recommendation = "hello"
    if pomodoro.get("running"):
        state, label, message, recommendation = "focus", "专注陪伴", "专注进行中，我会安静陪着你。", "rest"
    elif clock.get("live_state") == "away" or today.get("state") == "away":
        state, label, message, recommendation = "rest", "休息中", "先放松一下，回来后我们再继续。", "hello"
    elif _goal_done(dashboard.get("goals_progress")):
        state, label, message, recommendation = "celebrate", "达成时刻", "今天的目标完成了，做得很好！", "celebrate"
    elif active >= 25 * 60:
        state, label, message, recommendation = "steady", "稳定投入", "已经坚持一段时间了，节奏很好。", "rest"
    if behavior == "focus" and state in ("companion", "steady"):
        state, label, message = "focus", "专注陪伴", "我会少说一点，专心陪你。"
    if behavior == "quiet":
        message = "安静陪伴中。"
    return {
        "state": state,
        "label": label,
        "message": message,
        "recommendation": recommendation,
        "behavior": behavior,
        "active_seconds": active,
        "focus_ratio": round(focus_ratio, 1),
        "switches": int(dashboard.get("app_switches") or 0),
        "pomodoro": {"running": bool(pomodoro.get("running")), "mode": pomodoro.get("mode") or "idle", "remaining": int(pomodoro.get("remaining") or 0)},
        "updated_at": now,
    }
