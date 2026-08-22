# -*- coding: utf-8 -*-
"""本地番茄钟（内存计时，设置写入 meta，不联网）。"""
import threading
import time

DEFAULT_FOCUS_MIN = 25
DEFAULT_BREAK_MIN = 5
MIN_FOCUS = 1
MAX_FOCUS = 180
MIN_BREAK = 1
MAX_BREAK = 60

_lock = threading.RLock()
_state = {
    "mode": "idle",
    "remain": 0.0,
    "focus_sec": DEFAULT_FOCUS_MIN * 60,
    "break_sec": DEFAULT_BREAK_MIN * 60,
    "paused_from": None,
    "updated": 0.0,
    "last_event": None,
    "last_event_at": 0.0,
    "speech_event": None,
}


def _clamp_min(value, lo, hi, default):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        n = default
    if n < lo:
        n = lo
    if n > hi:
        n = hi
    return n


def _now(now):
    return time.time() if now is None else float(now)


def _emit_alert(evt):
    def _run():
        try:
            import sound_util
            sound_util.play_alert()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()
    _state["last_event"] = evt
    _state["last_event_at"] = time.time()
    _state["speech_event"] = evt


def _advance_locked():
    mode = _state["mode"]
    _state["remain"] = 0.0
    if mode == "focus":
        _state["mode"] = "break"
        _state["remain"] = float(_state["break_sec"])
        _state["paused_from"] = None
        evt = "focus_done"
    else:
        _state["mode"] = "idle"
        _state["paused_from"] = None
        evt = "break_done"
    _emit_alert(evt)
    return evt


def _sync_locked(now):
    if _state["mode"] not in ("focus", "break"):
        return None
    dt = now - _state["updated"]
    if dt < 0:
        dt = 0.0
    _state["remain"] -= dt
    _state["updated"] = now
    if _state["remain"] > 0:
        return None
    evt = _advance_locked()
    _state["updated"] = now
    return evt


def snapshot(now=None):
    now = _now(now)
    with _lock:
        _sync_locked(now)
        remain = max(0, int(round(_state["remain"])))
        return {
            "mode": _state["mode"],
            "remain": remain,
            "focus_min": max(1, int(round(_state["focus_sec"] / 60.0))),
            "break_min": max(1, int(round(_state["break_sec"] / 60.0))),
            "focus_sec": int(_state["focus_sec"]),
            "break_sec": int(_state["break_sec"]),
            "paused_from": _state["paused_from"],
            "last_event": _state["last_event"],
            "last_event_at": _state["last_event_at"],
            "label": format_overlay({
                "mode": _state["mode"],
                "remain": remain,
            }) or "未开始",
        }


def tick(now=None):
    now = _now(now)
    with _lock:
        return _sync_locked(now)


def start(focus_min=None, break_min=None, now=None, focus_sec=None, break_sec=None):
    now = _now(now)
    with _lock:
        if focus_sec is not None:
            try:
                _state["focus_sec"] = max(1, int(round(float(focus_sec))))
            except (TypeError, ValueError):
                pass
        elif focus_min is not None:
            _state["focus_sec"] = _clamp_min(focus_min, MIN_FOCUS, MAX_FOCUS, DEFAULT_FOCUS_MIN) * 60
        if break_sec is not None:
            try:
                _state["break_sec"] = max(1, int(round(float(break_sec))))
            except (TypeError, ValueError):
                pass
        elif break_min is not None:
            _state["break_sec"] = _clamp_min(break_min, MIN_BREAK, MAX_BREAK, DEFAULT_BREAK_MIN) * 60
        _state["mode"] = "focus"
        _state["remain"] = float(_state["focus_sec"])
        _state["paused_from"] = None
        _state["updated"] = now
        return snapshot(now)


def take_speech_event():
    with _lock:
        evt = _state.get("speech_event")
        _state["speech_event"] = None
        return evt


def simulate(kind="focus_done"):
    kind = kind if kind in ("focus_done", "break_done") else "focus_done"
    with _lock:
        _emit_alert(kind)
    return snapshot()


def toggle_pause(now=None):
    now = _now(now)
    with _lock:
        evt = _sync_locked(now)
        if _state["mode"] in ("focus", "break"):
            _state["paused_from"] = _state["mode"]
            _state["mode"] = "paused"
            _state["updated"] = now
        elif _state["mode"] == "paused":
            back = _state["paused_from"] or "focus"
            _state["mode"] = back
            _state["paused_from"] = None
            _state["updated"] = now
        return evt


def stop(now=None):
    now = _now(now)
    with _lock:
        _state["mode"] = "idle"
        _state["remain"] = 0.0
        _state["paused_from"] = None
        _state["updated"] = now
        return snapshot(now)


def format_overlay(snap=None):
    snap = snap or snapshot()
    mode = snap.get("mode")
    remain = max(0, int(snap.get("remain") or 0))
    mm, ss = remain // 60, remain % 60
    clock = "%02d:%02d" % (mm, ss)
    if mode == "focus":
        return "专注 " + clock
    if mode == "break":
        return "休息 " + clock
    if mode == "paused":
        return "暂停 " + clock
    return ""


def load_from_store(store):
    focus, brk = DEFAULT_FOCUS_MIN, DEFAULT_BREAK_MIN
    if store:
        try:
            focus = _clamp_min(store.get_meta("pomodoro_focus_min"), MIN_FOCUS, MAX_FOCUS, DEFAULT_FOCUS_MIN)
        except Exception:
            focus = DEFAULT_FOCUS_MIN
        try:
            brk = _clamp_min(store.get_meta("pomodoro_break_min"), MIN_BREAK, MAX_BREAK, DEFAULT_BREAK_MIN)
        except Exception:
            brk = DEFAULT_BREAK_MIN
    with _lock:
        if _state["mode"] == "idle":
            _state["focus_sec"] = focus * 60
            _state["break_sec"] = brk * 60
    return focus, brk


def save_to_store(store, focus_min=None, break_min=None):
    focus = _clamp_min(focus_min, MIN_FOCUS, MAX_FOCUS, DEFAULT_FOCUS_MIN)
    brk = _clamp_min(break_min, MIN_BREAK, MAX_BREAK, DEFAULT_BREAK_MIN)
    if store:
        store.set_meta("pomodoro_focus_min", str(focus))
        store.set_meta("pomodoro_break_min", str(brk))
    with _lock:
        if _state["mode"] == "idle":
            _state["focus_sec"] = focus * 60
            _state["break_sec"] = brk * 60
    return focus, brk
