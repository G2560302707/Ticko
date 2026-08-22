# -*- coding: utf-8 -*-
"""
Ticko - 主程序（采集端 + 本地面板服务）
纯标准库实现，无需联网、无需安装任何依赖。

规则（V1）：
- 每 3 秒采样焦点窗口与键鼠空闲
- 连续 5 分钟无输入后进入离开；触发前的 5 分钟仍计为活跃（不回溯）
- 离开期间焦点变化不切换应用计时器
- 锁屏 / 屏保强制视为离开
- 休眠不计入三本账，使 system = active + away
- 跨日在午夜切开
- 心跳写入 SQLite，异常退出按最后心跳结算，避免丢掉当前区间
"""
import atexit
import ctypes
import datetime
import email
from email import policy as email_policy
import hashlib
import http.server
import io
import json
import logging
import msvcrt
import os
import re
import shutil
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser

from ctypes import wintypes

# ------------------------- 配置 -------------------------
SAMPLE_INTERVAL = 3
AWAY_THRESHOLD = 300
SLEEP_THRESHOLD = 30
SNAPSHOT_KEEP_DAYS = 30
SEGMENT_KEEP_DAYS = 365
PORT = 8765

LOCK_PROCESS_NAMES = frozenset({
    "lockapp.exe",
    "logonui.exe",
    "screensaver.exe",
})

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import classify as classify_mod
import companion
import companion_ai
import companion_templates
import goals_util
import pet_engine
import pet_packs
import pomodoro_util
import sound_util
import speech_util
import theme_util
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "usage.db")
LOG_PATH = os.path.join(DATA_DIR, "app.log")
PID_PATH = os.path.join(DATA_DIR, "app.pid")
URL_PATH = os.path.join(DATA_DIR, "url.txt")
LOCK_PATH = os.path.join(DATA_DIR, "instance.lock")
DASHBOARD_PATH = os.path.join(SCRIPT_DIR, "dashboard.html")
COMPANION_CHAT_PATH = os.path.join(SCRIPT_DIR, "companion_chat.html")
ECHARTS_PATH = os.path.join(SCRIPT_DIR, "echarts.min.js")
PET_DIR = os.path.join(SCRIPT_DIR, "pet")
PET_HTML = os.path.join(PET_DIR, "pet.html")
PET_SPRITES = os.path.join(PET_DIR, "sprites")
PET_SPRITE_RE = re.compile(r"^(front|side|back|icon)(_\d+)?\.png$")

THEMES_DIR = os.path.join(DATA_DIR, "themes")
PET_PACKS_DIR = os.path.join(DATA_DIR, "pets")
APP_ICONS_DIR = os.path.join(DATA_DIR, "app_icons")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(THEMES_DIR, exist_ok=True)
os.makedirs(APP_ICONS_DIR, exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("usage")

_pet_hooks = {"show": None, "hide": None, "settings": None, "action": None}
_app_icon_lock = threading.Lock()


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


def _running_exe_path(exe_name):
    """返回匹配进程的完整 exe 路径，只用于读取 Windows 原始应用图标。"""
    if not PLATFORM_OK or not exe_name or any(x in exe_name for x in "\\/:"):
        return None
    target = str(exe_name).lower()
    kernel = ctypes.windll.kernel32
    snap = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if snap in (0, -1):
        return None
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == target:
                handle = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buf))
                        if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            return buf.value
                    finally:
                        kernel.CloseHandle(handle)
            ok = kernel.Process32NextW(snap, ctypes.byref(entry))
    except Exception:
        return None
    finally:
        try:
            kernel.CloseHandle(snap)
        except Exception:
            pass
    return None


def _app_icon_file(exe_name):
    """从正在运行的 exe 提取原始 Windows 图标，保存为本地 PNG 缓存。"""
    safe = os.path.basename(str(exe_name or "")).lower()
    if not safe or not re.match(r"^[\w .()\-]+\.exe$", safe, re.I):
        return None
    cache = os.path.join(APP_ICONS_DIR, hashlib.sha256(safe.encode("utf-8")).hexdigest()[:24] + ".png")
    if os.path.isfile(cache):
        return cache
    with _app_icon_lock:
        if os.path.isfile(cache):
            return cache
        exe_path = _running_exe_path(safe)
        if not exe_path or not os.path.isfile(exe_path):
            return None
        try:
            import clr
            clr.AddReference("System.Drawing")
            from System.Drawing import Icon
            from System.Drawing.Imaging import ImageFormat
            from System.IO import MemoryStream
            icon = Icon.ExtractAssociatedIcon(exe_path)
            if icon is None:
                return None
            stream = MemoryStream()
            try:
                icon.ToBitmap().Save(stream, ImageFormat.Png)
                with open(cache, "wb") as f:
                    f.write(bytes(bytearray(stream.ToArray())))
            finally:
                stream.Close()
                icon.Dispose()
            return cache if os.path.isfile(cache) else None
        except Exception as e:
            log.debug("应用图标提取失败 %s: %s", safe, e)
            return None
_pet_hook_lock = threading.Lock()


def register_pet_hooks(show_fn=None, hide_fn=None, settings_fn=None, action_fn=None):
    with _pet_hook_lock:
        _pet_hooks["show"] = show_fn
        _pet_hooks["hide"] = hide_fn
        _pet_hooks["settings"] = settings_fn
        _pet_hooks["action"] = action_fn


def apply_pet_visibility(show):
    with _pet_hook_lock:
        fn = _pet_hooks["show"] if show else _pet_hooks["hide"]
    if not fn:
        return False
    try:
        fn()
        return True
    except Exception:
        log.warning("桌宠显隐回调失败", exc_info=True)
        return False


def apply_pet_settings(settings):
    with _pet_hook_lock:
        fn = _pet_hooks["settings"]
    if not fn:
        return False
    try:
        fn(dict(settings or {}))
        return True
    except Exception:
        log.warning("桌宠设置回调失败", exc_info=True)
        return False


def apply_companion_action(action, snapshot=None):
    with _pet_hook_lock:
        fn = _pet_hooks["action"]
    if not fn:
        return False
    try:
        return bool(fn(str(action or ""), dict(snapshot or {})))
    except Exception:
        log.warning("伙伴动作回调失败", exc_info=True)
        return False


def pet_settings_from_store(store):
    mode = store.get_meta("pet_mode") or "wander"
    if mode not in pet_engine.MODES:
        mode = "wander"
    size = store.get_meta("pet_size") or "小"
    if size not in ("小", "中", "大"):
        size = "小"
    speech = store.get_meta("pet_speech") or "normal"
    if speech not in pet_engine.SPEECH_LEVELS:
        speech = "normal"
    lines = list(pet_engine.normalize_custom_lines(store.get_meta("pet_lines") or ""))
    pack_id = pet_packs.normalize_selected(PET_PACKS_DIR, store.get_meta("pet_pack") or "default")
    return {
        "pet_mode": mode,
        "pet_size": size,
        "pet_speech": speech,
        "pet_lines": lines,
        "pet_pack": pack_id,
    }


def companion_ai_settings_from_store(store, include_secret=False):
    settings = companion_ai.public_settings(store.get_meta)
    settings["proactive_enabled"] = (store.get_meta("ai_proactive_enabled") or "1") == "1"
    settings["voice_enabled"] = (store.get_meta("ai_voice_enabled") or "1") == "1"
    settings["voice_input_enabled"] = (store.get_meta("ai_voice_input_enabled") or "1") == "1"
    try:
        settings["voice_rate"] = max(-4, min(4, int(store.get_meta("ai_voice_rate") or 0)))
    except Exception:
        settings["voice_rate"] = 0
    preset = store.get_meta("ai_voice_preset") or "cute"
    settings["voice_preset"] = preset if preset in speech_util.VOICE_PRESETS else "cute"
    settings["speech"] = speech_util.status()
    if include_secret:
        settings["api_key"] = store.get_meta("ai_api_key") or ""
    return settings


def companion_history_from_store(store):
    try:
        items = json.loads(store.get_meta("ai_history") or "[]")
    except Exception:
        items = []
    clean = []
    for item in items if isinstance(items, list) else []:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = companion_ai.clean_text(item.get("content"), companion_ai.MAX_REPLY)
        if content:
            # 旧版本在模型额度耗尽时会重复写入同一句本地庆祝语；不再把它反复显示或喂回模型。
            if role == "assistant" and clean and clean[-1].get("role") == role and clean[-1].get("content") == content:
                continue
            clean.append({"role": role, "content": content})
    return clean[-companion_ai.MAX_HISTORY:]


def companion_templates_from_store(store):
    try:
        raw = json.loads(store.get_meta("offline_reply_templates") or "[]")
    except Exception:
        raw = []
    return companion_templates.normalize_custom(raw)


def companion_action_reply(snapshot, action):
    """伙伴控制台的即时动作台词，保持与当日数据和动作一致。"""
    active = max(0, int((snapshot or {}).get("active_seconds") or 0) // 60)
    switches = max(0, int((snapshot or {}).get("switches") or 0))
    lines = {
        "hello": "你好，我在呢。今天已经有效投入 %d 分钟了。" % active,
        "walk": "我们去走走吧。今天已经切换 %d 次，活动一下再回来继续。" % switches,
        "celebrate": "做得漂亮，今天的每一点投入都值得庆祝。",
        "rest": "先休息一会儿，回来以后我们再继续。",
        "home": "我先回到角落等你。需要时，随时叫我。",
    }
    return lines.get(action, "我在这里陪着你。")


def companion_ai_usage_from_store(store, level="medium"):
    today = date_str(time.time())
    try:
        usage = json.loads(store.get_meta("ai_usage") or "{}")
    except Exception:
        usage = {}
    if usage.get("date") != today:
        usage = {"date": today, "requests": 0, "estimated_tokens": 0, "auto_events": 0}
    policy = companion_ai.level_policy(level)
    return {
        "requests": max(0, int(usage.get("requests") or 0)),
        "estimated_tokens": max(0, int(usage.get("estimated_tokens") or 0)),
        "auto_events": max(0, int(usage.get("auto_events") or 0)),
        "request_limit": policy["daily_requests"],
        "level": companion_ai.normalize_interaction_level(level),
    }


def record_companion_ai_usage(store, level, request_text, reply_text, auto=False):
    usage = companion_ai_usage_from_store(store, level)
    usage["requests"] += 1
    if auto:
        usage["auto_events"] += 1
    # 中文按约两个字符一个 token 的保守估算；用于额度展示，不冒充服务商账单。
    usage["estimated_tokens"] += max(1, (len(request_text or "") + len(reply_text or "")) // 2)
    store.set_meta("ai_usage", json.dumps({"date": date_str(time.time()), "requests": usage["requests"], "estimated_tokens": usage["estimated_tokens"], "auto_events": usage["auto_events"]}, ensure_ascii=False))
    return usage


def maybe_companion_auto_reply(store, dashboard, pomodoro, behavior, trigger):
    """仅在中/重度模式的状态切换时生成一次主动回应，调用方应放在后台线程。"""
    settings = companion_ai_settings_from_store(store, include_secret=True)
    level = settings["interaction_level"]
    policy = companion_ai.level_policy(level)
    if level == "light" or not settings["proactive_enabled"] or not settings["enabled"] or settings["provider"] == "off":
        return None
    usage = companion_ai_usage_from_store(store, level)
    now = time.time()
    try:
        last = float(store.get_meta("ai_auto_last_ts") or 0)
    except Exception:
        last = 0
    if usage["requests"] >= usage["request_limit"] or usage["auto_events"] >= policy["auto_events"] or now - last < policy["cooldown"]:
        return None
    snapshot = companion.build_snapshot(dashboard, pomodoro, behavior)
    if settings.get("share_app"):
        snapshot["current_app"] = (dashboard.get("status") or {}).get("app") or ""
    history = companion_history_from_store(store)
    prompt = "现在是%s。请主动给我一句简短陪伴，不要解释数据来源。" % (snapshot.get("label") or trigger)
    reply = companion_ai.generate(settings, snapshot, prompt, history, snapshot.get("recommendation"), companion_templates_from_store(store))
    if reply.get("source") != "model":
        return None
    store.set_meta("ai_auto_last_ts", str(now))
    record_companion_ai_usage(store, level, prompt, reply["reply"], auto=True)
    history.append({"role": "assistant", "content": reply["reply"]})
    store.set_meta("ai_history", json.dumps(history[-companion_ai.MAX_HISTORY:], ensure_ascii=False))
    snapshot["reply"] = reply["reply"]
    snapshot.pop("current_app", None)
    speech_util.speak_async(reply["reply"], settings["voice_enabled"], settings["voice_rate"], settings["voice_preset"])
    return {"action": reply.get("action") or "hello", "snapshot": snapshot}


def live_elapsed(live_start, now):
    if live_start is None:
        return 0.0
    return max(0.0, float(now) - float(live_start))


def paint_totals(active_closed, away_closed, system_closed, live_start, live_state, now):
    """已入账时长 + 当前未闭合区间。显示层只做 floor，不再叠加第二份 live。"""
    el = live_elapsed(live_start, now)
    active = float(active_closed or 0)
    away = float(away_closed or 0)
    system = float(system_closed or 0)
    if live_state == "active":
        active += el
        system += el
    elif live_state == "away":
        away += el
        system += el
    return active, away, system


# ------------------------- Windows 平台接口 -------------------------
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


PLATFORM_OK = False
user32 = None
kernel32 = None

try:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    user32.GetLastInputInfo.restype = wintypes.BOOL
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    ]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetTickCount.argtypes = []
    kernel32.GetTickCount.restype = wintypes.DWORD
    kernel32.GetTickCount64.argtypes = []
    kernel32.GetTickCount64.restype = ctypes.c_uint64

    PLATFORM_OK = True
except Exception as e:
    log.warning("非 Windows 平台，采集功能不可用: %s", e)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_SWITCHDESKTOP = 0x0100
UOI_NAME = 2
SPI_GETSCREENSAVERRUNNING = 0x0072


def get_foreground():
    """返回 (应用名/exe基名, 窗口标题)。"""
    if not PLATFORM_OK:
        return None, None
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None, None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        app = None
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if hproc:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                app = os.path.basename(buf.value)
            kernel32.CloseHandle(hproc)
        title = None
        try:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                tbuf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, tbuf, length + 1)
                title = tbuf.value
        except Exception:
            title = None
        return app, title
    except Exception as e:
        log.debug("get_foreground error: %s", e)
        return None, None


def get_idle_seconds():
    """距上次键盘/鼠标输入的秒数（32 位 tick 回绕安全）。"""
    if not PLATFORM_OK:
        return 0
    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        now32 = kernel32.GetTickCount()
        idle_ms = (now32 - info.dwTime) & 0xFFFFFFFF
        return idle_ms / 1000.0
    except Exception:
        return 0


def get_tick_seconds():
    if not PLATFORM_OK:
        return time.time()
    try:
        return kernel32.GetTickCount64() / 1000.0
    except Exception:
        return time.time()


def is_screensaver_running():
    if not PLATFORM_OK:
        return False
    try:
        flag = wintypes.BOOL(False)
        if user32.SystemParametersInfoW(SPI_GETSCREENSAVERRUNNING, 0, ctypes.byref(flag), 0):
            return bool(flag.value)
    except Exception:
        pass
    return False


def is_session_locked():
    """输入桌面名称不是 Default 时视为锁屏。打开失败不判定为离开，避免误伤。"""
    if not PLATFORM_OK:
        return False
    try:
        handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not handle:
            return False
        try:
            needed = wintypes.DWORD()
            buf = ctypes.create_unicode_buffer(256)
            ok = user32.GetUserObjectInformationW(
                handle, UOI_NAME, buf, 256 * 2, ctypes.byref(needed)
            )
            if not ok:
                return False
            name = (buf.value or "").lower()
            return name not in ("default",)
        finally:
            user32.CloseDesktop(handle)
    except Exception:
        return False


def today_start_ts(now=None):
    now = time.time() if now is None else now
    return datetime.datetime.combine(
        datetime.datetime.fromtimestamp(now).date(), datetime.time.min
    ).timestamp()


def hour_credits(start, end, day_start):
    """把 [start,end) 落到当天 24 个小时桶，返回长度 24 的秒数列表。"""
    buckets = [0.0] * 24
    day_end = day_start + 86400.0
    t = max(start, day_start)
    e = min(end, day_end)
    while t < e - 1e-9:
        hour = int((t - day_start) // 3600)
        if hour < 0 or hour > 23:
            break
        slot_end = min(e, day_start + (hour + 1) * 3600)
        buckets[hour] += slot_end - t
        t = slot_end
    return buckets


# ------------------------- 数据库 -------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL,
  app_name TEXT,
  window_title TEXT,
  state TEXT,
  idle_seconds REAL
);
CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_ts REAL,
  end_ts REAL,
  app_name TEXT,
  state TEXT,
  window_title TEXT,
  category TEXT
);
CREATE TABLE IF NOT EXISTS category_daily_stats (
  date TEXT,
  category TEXT,
  active_seconds REAL DEFAULT 0,
  PRIMARY KEY (date, category)
);
CREATE TABLE IF NOT EXISTS daily_stats (
  date TEXT PRIMARY KEY,
  active_seconds REAL DEFAULT 0,
  away_seconds REAL DEFAULT 0,
  system_seconds REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS app_daily_stats (
  date TEXT,
  app_name TEXT,
  active_seconds REAL DEFAULT 0,
  PRIMARY KEY (date, app_name)
);
CREATE TABLE IF NOT EXISTS state_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL,
  from_state TEXT,
  to_state TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE INDEX IF NOT EXISTS idx_seg_start ON segments(start_ts);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts);
"""


def date_str(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def next_midnight(ts):
    dt = datetime.datetime.fromtimestamp(ts)
    nxt = datetime.datetime.combine(dt.date() + datetime.timedelta(days=1), datetime.time.min)
    return nxt.timestamp()


class Storage:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.lock = threading.Lock()
        self._ignore_cfg = None
        self._goals_cfg = None
        self._migrate()

    def _migrate(self):
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(segments)").fetchall()}
        if "window_title" not in cols:
            self.conn.execute("ALTER TABLE segments ADD COLUMN window_title TEXT")
        if "category" not in cols:
            self.conn.execute("ALTER TABLE segments ADD COLUMN category TEXT")
        self.conn.commit()

    def _exec(self, sql, params=()):
        with self.lock:
            self.conn.execute(sql, params)
            self.conn.commit()

    def insert_snapshot(self, ts, app, title, state, idle):
        self._exec(
            "INSERT INTO snapshots(ts, app_name, window_title, state, idle_seconds) VALUES(?,?,?,?,?)",
            (ts, app, title, state, idle),
        )

    def insert_segment(self, start, end, app, state, title=None, category=None):
        self._exec(
            "INSERT INTO segments(start_ts, end_ts, app_name, state, window_title, category) VALUES(?,?,?,?,?,?)",
            (start, end, app, state, title, category),
        )

    def add_category(self, date, category, active):
        if not category:
            return
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO category_daily_stats(date, category) VALUES(?,?)",
                (date, category),
            )
            self.conn.execute(
                "UPDATE category_daily_stats SET active_seconds=active_seconds+? WHERE date=? AND category=?",
                (active, date, category),
            )
            self.conn.commit()

    def rules(self):
        return classify_mod.load_rules_json(self.get_meta("classify_rules"))

    def save_rules(self, rules):
        overlay = classify_mod._user_overlay(rules if isinstance(rules, dict) else {})
        self.set_meta("classify_rules", json.dumps(overlay, ensure_ascii=False))
        return classify_mod.normalize_rules(overlay)

    def rules_editor(self):
        text = self.get_meta("classify_rules")
        try:
            raw = json.loads(text) if text else {}
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return classify_mod.editor_rules(raw)

    def reclassify_day(self, date):
        rules = self.rules()
        ignore_cfg = self.ignore_config()
        day = datetime.datetime.strptime(date, "%Y-%m-%d")
        start = datetime.datetime.combine(day.date(), datetime.time.min).timestamp()
        end = start + 86400
        with self.lock:
            self.conn.execute("DELETE FROM category_daily_stats WHERE date=?", (date,))
            rows = self.conn.execute(
                "SELECT id, start_ts, end_ts, app_name, window_title FROM segments WHERE state='active' AND start_ts < ? AND end_ts > ?",
                (end, start),
            ).fetchall()
            for sid, st, et, app, title in rows:
                cat = classify_mod.classify(app, title, rules)
                self.conn.execute("UPDATE segments SET category=? WHERE id=?", (cat, sid))
                dur = max(0.0, min(et, end) - max(st, start))
                if cat and dur > 0 and goals_util.should_credit_app(app, dur, ignore_cfg):
                    self.conn.execute(
                        "INSERT OR IGNORE INTO category_daily_stats(date, category) VALUES(?,?)",
                        (date, cat),
                    )
                    self.conn.execute(
                        "UPDATE category_daily_stats SET active_seconds=active_seconds+? WHERE date=? AND category=?",
                        (dur, date, cat),
                    )
            self.conn.commit()
        return True

    def add_daily(self, date, active=0.0, away=0.0, system=0.0):
        with self.lock:
            self.conn.execute("INSERT OR IGNORE INTO daily_stats(date) VALUES(?)", (date,))
            self.conn.execute(
                "UPDATE daily_stats SET active_seconds=active_seconds+?, away_seconds=away_seconds+?, system_seconds=system_seconds+? WHERE date=?",
                (active, away, system, date),
            )
            self.conn.commit()

    def add_app(self, date, app, active):
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO app_daily_stats(date, app_name) VALUES(?,?)", (date, app)
            )
            self.conn.execute(
                "UPDATE app_daily_stats SET active_seconds=active_seconds+? WHERE date=? AND app_name=?",
                (active, date, app),
            )
            self.conn.commit()

    def add_transition(self, ts, frm, to):
        if frm == to:
            return
        self._exec(
            "INSERT INTO state_transitions(ts, from_state, to_state) VALUES(?,?,?)",
            (ts, frm, to),
        )

    def set_meta(self, key, value):
        self._exec("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))
        if key in ("ignore_apps", "ignore_min_seconds", "daily_goals"):
            self._ignore_cfg = None
            self._goals_cfg = None

    def ignore_config(self):
        if self._ignore_cfg is None:
            apps_raw = self.get_meta("ignore_apps")
            self._ignore_cfg = goals_util.normalize_ignore_config(
                apps_raw,
                self.get_meta("ignore_min_seconds"),
                apps_missing=apps_raw is None,
            )
        return self._ignore_cfg

    def should_credit_app(self, app, duration=None):
        return goals_util.should_credit_app(app, duration, self.ignore_config())

    def daily_goals(self):
        if self._goals_cfg is None:
            self._goals_cfg = goals_util.normalize_daily_goals(self.get_meta("daily_goals"))
        return self._goals_cfg

    def save_ignore_config(self, apps_raw, min_raw=None):
        cfg = goals_util.normalize_ignore_config(apps_raw, min_raw, apps_missing=False)
        self.set_meta("ignore_apps", json.dumps(cfg["apps"], ensure_ascii=False))
        self.set_meta("ignore_min_seconds", str(cfg["min_seconds"]))
        return cfg

    def save_daily_goals(self, raw):
        goals = goals_util.normalize_daily_goals(raw)
        self.set_meta("daily_goals", json.dumps(goals, ensure_ascii=False))
        return goals

    def get_meta(self, key, default=None):
        rows = self.read("SELECT value FROM meta WHERE key=?", (key,))
        if not rows:
            return default
        return rows[0][0]

    def clear_open(self):
        with self.lock:
            self.conn.execute("DELETE FROM meta WHERE key LIKE 'open_%' OR key='heartbeat_ts'")
            self.conn.commit()

    def save_open(self, ts, seg):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('heartbeat_ts', ?)", (str(ts),))
            if seg is None:
                self.conn.execute("DELETE FROM meta WHERE key LIKE 'open_%'")
            else:
                payload = json.dumps(seg, ensure_ascii=False)
                self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('open_segment', ?)", (payload,))
            self.conn.commit()

    def load_open(self):
        raw = self.get_meta("open_segment")
        hb = self.get_meta("heartbeat_ts")
        if not raw or not hb:
            return None, None
        try:
            return json.loads(raw), float(hb)
        except Exception:
            return None, None

    def cleanup(self):
        now = time.time()
        snap_cut = now - SNAPSHOT_KEEP_DAYS * 86400
        seg_cut = now - SEGMENT_KEEP_DAYS * 86400
        with self.lock:
            self.conn.execute("DELETE FROM snapshots WHERE ts < ?", (snap_cut,))
            self.conn.execute("DELETE FROM segments WHERE end_ts < ?", (seg_cut,))
            self.conn.commit()

    def read(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            return cur.fetchall()


# ------------------------- 状态机 / 计时器 -------------------------
class Tracker:
    def __init__(self, storage):
        self.store = storage
        self.cur = None
        self.prev_wall = None
        self.prev_tick = None
        self.last_cleanup = 0
        self._finalized = False
        self._recover()

    def _recover(self):
        seg, hb = self.store.load_open()
        if not seg or hb is None:
            return
        start = float(seg.get("start") or 0)
        if hb > start:
            self._close(seg, hb)
            log.info("从心跳恢复未闭合区间 %.1f 秒", hb - start)
        self.store.clear_open()

    def tick(self):
        now = time.time()
        tick = get_tick_seconds()
        idle = get_idle_seconds()
        locked = is_session_locked() or is_screensaver_running()
        app, title = get_foreground()
        if app and app.lower() in LOCK_PROCESS_NAMES:
            locked = True

        state = "away" if (idle >= AWAY_THRESHOLD or locked) else "active"
        cat = classify_mod.classify(app, title, self.store.rules()) if state == "active" else None

        if self.prev_wall is not None:
            gap = (now - self.prev_wall) - (tick - self.prev_tick)
            if gap > SLEEP_THRESHOLD:
                if self.cur is not None:
                    self._close(self.cur, self.prev_wall)
                    self.cur = None
                self.store.insert_segment(self.prev_wall, now, None, "sleep")
                self.store.add_transition(now, "sleep_gap", "sleep")
                log.info("检测到休眠/睡眠，跳过 %.1f 秒", gap)

        self.prev_wall = now
        self.prev_tick = tick
        self.store.insert_snapshot(now, app, title, state, idle)

        if self.cur is None:
            self.cur = {"app": app, "state": state, "start": now, "title": title, "category": cat}
        else:
            need_split = (state != self.cur["state"]) or (
                state == "active"
                and (app != self.cur["app"] or cat != self.cur.get("category"))
            )
            crossed_midnight = date_str(self.cur["start"]) != date_str(now)
            if need_split or crossed_midnight:
                old_state = self.cur["state"]
                self._close(self.cur, now)
                if need_split:
                    self.store.add_transition(now, old_state, state)
                self.cur = {"app": app, "state": state, "start": now, "title": title, "category": cat}

        self.store.save_open(now, self.cur)

        if now - self.last_cleanup > 3600:
            self.store.cleanup()
            self.last_cleanup = now

    def _close(self, seg, end):
        start = float(seg["start"])
        if end <= start:
            return
        st = seg.get("state")
        app = seg.get("app")
        cursor = start
        while cursor < end - 1e-9:
            chunk_end = min(end, next_midnight(cursor))
            dur = chunk_end - cursor
            if dur <= 0:
                break
            d = date_str(cursor)
            if st == "active":
                self.store.add_daily(d, active=dur, system=dur)
                if self.store.should_credit_app(app, dur):
                    if app:
                        self.store.add_app(d, app, dur)
                    if seg.get("category"):
                        self.store.add_category(d, seg.get("category"), dur)
            elif st == "away":
                self.store.add_daily(d, away=dur, system=dur)
            self.store.insert_segment(
                cursor,
                chunk_end,
                app if st != "sleep" else None,
                st,
                seg.get("title"),
                seg.get("category") if st == "active" else None,
            )
            cursor = chunk_end

    def finalize(self):
        if self._finalized:
            return
        self._finalized = True
        if self.cur is not None:
            self._close(self.cur, time.time())
            self.cur = None
        self.store.clear_open()


def collector_loop(tracker, stop_event):
    log.info("采集线程启动")
    while not stop_event.is_set():
        try:
            tracker.tick()
        except Exception as e:
            log.error("tick error: %s", e)
        stop_event.wait(SAMPLE_INTERVAL)
    tracker.finalize()
    log.info("采集线程退出")


MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".ico": "image/x-icon",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def _theme_media_exists(theme_id, filename):
    if not filename:
        return False
    fpath = theme_util.safe_theme_path(THEMES_DIR, theme_id, filename)
    return bool(fpath and os.path.isfile(fpath))


def _prune_orphan_theme(folder):
    has_media = False
    try:
        for fn in os.listdir(folder):
            ext = os.path.splitext(fn)[1].lower()
            if ext in theme_util.ALLOWED_EXT and os.path.isfile(os.path.join(folder, fn)):
                has_media = True
                break
    except Exception:
        pass
    if has_media:
        return
    try:
        import shutil

        shutil.rmtree(folder)
    except Exception:
        pass


def list_theme_packs():
    items = []
    if not os.path.isdir(THEMES_DIR):
        return items
    for name in sorted(os.listdir(THEMES_DIR)):
        folder = os.path.join(THEMES_DIR, name)
        if not os.path.isdir(folder) or not theme_util.THEME_ID_RE.match(name):
            continue
        meta = {"id": name, "name": name, "background": None, "overlay": 0.45, "colors": {}}
        cfg = os.path.join(folder, "theme.json")
        if os.path.isfile(cfg):
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    meta["name"] = data.get("name") or name
                    meta["background"] = data.get("background")
                    meta["overlay"] = float(data.get("overlay", 0.45))
                    if isinstance(data.get("colors"), dict):
                        meta["colors"] = data["colors"]
            except Exception:
                pass
        if not meta["background"]:
            try:
                for fn in os.listdir(folder):
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in theme_util.ALLOWED_EXT:
                        meta["background"] = fn
                        break
            except Exception:
                pass
        if not _theme_media_exists(name, meta.get("background")):
            _prune_orphan_theme(folder)
            continue
        items.append(meta)
    return items


def ensure_desktop_shortcut():
    marker = os.path.join(DATA_DIR, "shortcut_done")
    if os.path.exists(marker):
        return
    ps1 = os.path.join(BASE_DIR, "create_shortcut.ps1")
    if not os.path.isfile(ps1):
        return
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1],
            cwd=BASE_DIR,
            timeout=30,
            check=False,
        )
        with open(marker, "w", encoding="utf-8") as f:
            f.write("1")
    except Exception as e:
        log.warning("创建桌面快捷方式失败: %s", e)


def fmt_hms(seconds):
    seconds = int(max(0, seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return "%02d:%02d:%02d" % (h, m, s)


def build_category_breakdown(segs, categories=None, ignore_apps=None):
    names = list(categories or classify_mod.CATEGORIES)
    skipped = set((ignore_apps or ()))
    by_cat = {n: {"apps": {}, "titles": {}} for n in names}
    for seg in segs or []:
        if seg.get("state") != "active":
            continue
        cat = seg.get("category") or "其他"
        if cat not in by_cat:
            by_cat[cat] = {"apps": {}, "titles": {}}
        dur = max(0.0, float(seg.get("end") or 0) - float(seg.get("start") or 0))
        if dur <= 0:
            continue
        app = seg.get("app") or "无焦点"
        if (app or "").strip().lower() in skipped:
            continue
        title = (seg.get("title") or "").strip() or "（无标题）"
        by_cat[cat]["apps"][app] = by_cat[cat]["apps"].get(app, 0.0) + dur
        key = (app, title)
        by_cat[cat]["titles"][key] = by_cat[cat]["titles"].get(key, 0.0) + dur
    out = {}
    for cat, bucket in by_cat.items():
        total = sum(bucket["apps"].values()) or 1.0
        apps = []
        for name, sec in sorted(bucket["apps"].items(), key=lambda x: -x[1]):
            apps.append(
                {
                    "name": name,
                    "seconds": round(sec),
                    "fmt": fmt_hms(sec),
                    "percent": round(100.0 * sec / total, 1),
                }
            )
        titles = []
        ranked = sorted(bucket["titles"].items(), key=lambda x: -x[1])[:12]
        for (app, title), sec in ranked:
            titles.append(
                {
                    "app": app,
                    "title": title,
                    "seconds": round(sec),
                    "fmt": fmt_hms(sec),
                }
            )
        out[cat] = {"apps": apps, "titles": titles}
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    tracker = None
    store = None

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self._send(200, data, ctype)
        except Exception:
            self._send(404, b"not found")

    def _pet_sprite(self, url_path):
        name = os.path.basename(url_path.split("?")[0])
        if not PET_SPRITE_RE.match(name):
            self._send(404, b"not found")
            return
        fpath = os.path.abspath(os.path.join(PET_SPRITES, name))
        root = os.path.abspath(PET_SPRITES)
        if not fpath.startswith(root + os.sep) or not os.path.isfile(fpath):
            self._send(404, b"not found")
            return
        self._file(fpath, "image/png")

    def _theme_file(self, url_path):
        parts = [p for p in url_path.split("/") if p]
        if len(parts) != 3:
            self._send(404, b"not found")
            return
        _, tid, fname = parts
        fpath = theme_util.safe_theme_path(THEMES_DIR, tid, fname)
        if not fpath or not os.path.isfile(fpath):
            self._send(404, b"not found")
            return
        ext = os.path.splitext(fname)[1].lower()
        self._file(fpath, MIME.get(ext, "application/octet-stream"))

    def _app_icon(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        name = (query.get("name") or [""])[0]
        fpath = _app_icon_file(name)
        if not fpath:
            self._send(404, b"not found", "image/png")
            return
        self._file(fpath, "image/png")

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length > theme_util.MAX_UPLOAD:
            self._send(413, json.dumps({"ok": False, "error": "文件过大"}))
            return
        raw = self.rfile.read(length) if length else b""
        if path == "/api/rules":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send(400, json.dumps({"ok": False}))
                return
            rules = self.store.save_rules(data)
            self._send(200, json.dumps({"ok": True, "rules": rules}, ensure_ascii=False))
        elif path == "/api/reclassify":
            day = date_str(time.time())
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
                if data.get("date"):
                    day = data["date"]
            except Exception:
                pass
            self.store.reclassify_day(day)
            self._send(200, json.dumps({"ok": True, "date": day}))
        elif path == "/api/settings":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send(400, json.dumps({"ok": False}))
                return
            if "palette" in data:
                self.store.set_meta("palette", str(data.get("palette") or "midnight"))
            if "theme_id" in data:
                self.store.set_meta("theme_id", str(data.get("theme_id") or ""))
            if "overlay" in data:
                try:
                    ov = min(0.75, max(0.05, float(data.get("overlay"))))
                except Exception:
                    ov = 0.28
                self.store.set_meta("overlay", str(ov))
            if "show_pet" in data:
                show = bool(data.get("show_pet"))
                self.store.set_meta("show_pet", "1" if show else "0")
                apply_pet_visibility(show)
            if "companion_behavior" in data:
                self.store.set_meta(
                    "companion_behavior",
                    companion.normalize_behavior(data.get("companion_behavior")),
                )
            ai_keys = ("ai_enabled", "ai_provider", "ai_base_url", "ai_model", "ai_share_app", "ai_name", "ai_persona", "ai_custom_prompt", "ai_interaction_level", "ai_proactive_enabled", "ai_voice_enabled", "ai_voice_input_enabled", "ai_voice_rate", "ai_voice_preset")
            if any(k in data for k in ai_keys) or "ai_api_key" in data or data.get("clear_ai_api_key"):
                current_ai = companion_ai_settings_from_store(self.store)
                next_ai = companion_ai.validate_config(data, current_ai)
                self.store.set_meta("ai_enabled", "1" if next_ai["enabled"] else "0")
                self.store.set_meta("ai_provider", next_ai["provider"])
                self.store.set_meta("ai_base_url", next_ai["base_url"])
                self.store.set_meta("ai_model", next_ai["model"])
                self.store.set_meta("ai_share_app", "1" if next_ai["share_app"] else "0")
                self.store.set_meta("ai_name", next_ai["name"])
                self.store.set_meta("ai_persona", next_ai["persona"])
                self.store.set_meta("ai_custom_prompt", next_ai["custom_prompt"])
                self.store.set_meta("ai_interaction_level", next_ai["interaction_level"])
                self.store.set_meta("ai_proactive_enabled", "1" if bool(data.get("ai_proactive_enabled", current_ai["proactive_enabled"])) else "0")
                self.store.set_meta("ai_voice_enabled", "1" if bool(data.get("ai_voice_enabled", current_ai["voice_enabled"])) else "0")
                self.store.set_meta("ai_voice_input_enabled", "1" if bool(data.get("ai_voice_input_enabled", current_ai["voice_input_enabled"])) else "0")
                try:
                    voice_rate = max(-4, min(4, int(data.get("ai_voice_rate", current_ai["voice_rate"]))))
                except Exception:
                    voice_rate = current_ai["voice_rate"]
                self.store.set_meta("ai_voice_rate", str(voice_rate))
                voice_preset = str(data.get("ai_voice_preset", current_ai["voice_preset"]))
                self.store.set_meta("ai_voice_preset", voice_preset if voice_preset in speech_util.VOICE_PRESETS else "cute")
                if data.get("clear_ai_api_key"):
                    self.store.set_meta("ai_api_key", "")
                elif "ai_api_key" in data:
                    key = companion_ai.clean_text(data.get("ai_api_key"), 600)
                    if key:
                        self.store.set_meta("ai_api_key", key)
            pet_keys = ("pet_mode", "pet_size", "pet_speech", "pet_lines", "pet_pack")
            pet_changed = any(k in data for k in pet_keys)
            if pet_changed:
                current = pet_settings_from_store(self.store)
                mode = data.get("pet_mode", current["pet_mode"])
                size = data.get("pet_size", current["pet_size"])
                speech = data.get("pet_speech", current["pet_speech"])
                lines = data.get("pet_lines", current["pet_lines"])
                pack_id = pet_packs.normalize_selected(
                    PET_PACKS_DIR, str(data.get("pet_pack", current["pet_pack"]) or "default")
                )
                if mode not in pet_engine.MODES:
                    mode = current["pet_mode"]
                if size not in ("小", "中", "大"):
                    size = current["pet_size"]
                if speech not in pet_engine.SPEECH_LEVELS:
                    speech = current["pet_speech"]
                lines = list(pet_engine.normalize_custom_lines(lines))
                self.store.set_meta("pet_mode", mode)
                self.store.set_meta("pet_size", size)
                self.store.set_meta("pet_speech", speech)
                self.store.set_meta("pet_lines", json.dumps(lines, ensure_ascii=False))
                self.store.set_meta("pet_pack", pack_id)
            if "ignore_apps" in data or "ignore_min_seconds" in data:
                apps_raw = data["ignore_apps"] if "ignore_apps" in data else self.store.get_meta("ignore_apps")
                min_raw = data["ignore_min_seconds"] if "ignore_min_seconds" in data else self.store.get_meta("ignore_min_seconds")
                apps_missing = "ignore_apps" not in data and self.store.get_meta("ignore_apps") is None
                if "ignore_apps" in data:
                    apps_missing = False
                cfg = goals_util.normalize_ignore_config(apps_raw, min_raw, apps_missing=apps_missing)
                self.store.set_meta("ignore_apps", json.dumps(cfg["apps"], ensure_ascii=False))
                self.store.set_meta("ignore_min_seconds", str(cfg["min_seconds"]))
            if "daily_goals" in data:
                self.store.save_daily_goals(data.get("daily_goals"))
            settings = self.api_settings()
            if pet_changed:
                apply_pet_settings({k: settings[k] for k in pet_keys})
            self._send(200, json.dumps({"ok": True, "settings": settings}, ensure_ascii=False))
        elif path == "/api/pomodoro":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                data = {}
            action = str(data.get("action") or "")
            if action == "start":
                pomodoro_util.start(
                    data.get("focus_min"),
                    data.get("break_min"),
                    focus_sec=data.get("focus_sec"),
                    break_sec=data.get("break_sec"),
                )
            elif action in ("pause", "toggle"):
                pomodoro_util.toggle_pause()
            elif action == "stop":
                pomodoro_util.stop()
            elif action == "config":
                pomodoro_util.save_to_store(self.store, data.get("focus_min"), data.get("break_min"))
            elif action == "simulate":
                pomodoro_util.simulate(data.get("kind") or "focus_done")
            self._send(200, json.dumps({"ok": True, "pomodoro": pomodoro_util.snapshot()}, ensure_ascii=False))
        elif path == "/api/sounds":
            self._handle_sounds_post(raw)
        elif path == "/api/themes":
            self._handle_themes_post(raw)
        elif path == "/api/pets":
            self._handle_pet_packs_post(raw)
        elif path == "/api/companion/chat":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                data = {}
            self._send(200, json.dumps(self.api_companion_chat(data), ensure_ascii=False))
        elif path == "/api/companion/templates":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                data = {}
            self._send(200, json.dumps(self.api_companion_templates(data), ensure_ascii=False))
        elif path == "/api/companion/transcribe":
            settings = companion_ai_settings_from_store(self.store)
            if not settings.get("voice_input_enabled"):
                self._send(403, json.dumps({"ok": False, "error": "语音输入已关闭"}, ensure_ascii=False))
                return
            logging.info("收到伙伴语音：%s 字节，frames=%s，rms=%s", len(raw), self.headers.get("X-Ticko-Audio-Frames", "?"), self.headers.get("X-Ticko-Audio-Rms", "?"))
            text, error = speech_util.transcribe_wav(raw)
            logging.info("伙伴语音识别：%s", "成功" if text else (error or "无结果"))
            status = 200 if text else 400
            self._send(status, json.dumps({"ok": bool(text), "text": text, "error": error}, ensure_ascii=False))
        elif path == "/api/companion/listen":
            settings = companion_ai_settings_from_store(self.store)
            if not settings.get("voice_input_enabled"):
                self._send(403, json.dumps({"ok": False, "error": "语音输入已关闭"}, ensure_ascii=False))
            else:
                started = speech_util.listen_once_async()
                self._send(200, json.dumps({"ok": True, "started": started, "listen": speech_util.listen_status()}, ensure_ascii=False))
        elif path == "/api/companion/listen/stop":
            speech_util.stop_listening()
            self._send(200, json.dumps({"ok": True, "listen": speech_util.listen_status()}, ensure_ascii=False))
        elif path == "/api/companion/history":
            self.store.set_meta("ai_history", "[]")
            self._send(200, json.dumps({"ok": True, "history": []}, ensure_ascii=False))
        elif path == "/api/companion/test":
            settings = companion_ai_settings_from_store(self.store, include_secret=True)
            ok, message = companion_ai.test_connection(settings)
            self._send(200 if ok else 400, json.dumps({"ok": ok, "message": message}, ensure_ascii=False))
        elif path == "/api/companion":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                data = {}
            action = str(data.get("action") or "")
            if action not in companion.ACTION_NAMES:
                self._send(400, json.dumps({"ok": False, "error": "未知伙伴动作"}, ensure_ascii=False))
                return
            snap = self.api_companion()
            snap["reply"] = companion_action_reply(snap, action)
            applied = apply_companion_action(action, snap)
            settings = companion_ai_settings_from_store(self.store)
            # 控制台动作的朗读不依赖桌宠窗体回调：窗体初始化稍慢时，仍应立即说话。
            speech_util.speak_stream_async(snap["reply"], settings["voice_enabled"], settings["voice_rate"], settings["voice_preset"])
            self._send(200, json.dumps({"ok": True, "pet_applied": applied, "companion": snap}, ensure_ascii=False))
        elif path == "/api/shutdown":
            self._send(200, json.dumps({"ok": True}))
            request_shutdown()
        else:
            self._send(404, b"not found")

    def _send_sound_file(self):
        sid = ""
        if "?" in self.path:
            q = self.path.split("?", 1)[1]
            for part in q.split("&"):
                if part.startswith("id="):
                    sid = part.split("=", 1)[1]
                    break
        path = sound_util.resolve_path(sid)
        if not path:
            self._send(404, b"not found")
            return
        ext = os.path.splitext(path)[1].lower()
        self._file(path, MIME.get(ext, "application/octet-stream"))

    def _handle_sounds_post(self, raw):
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" in ctype.lower():
            header = ("Content-Type: %s\r\nMIME-Version: 1.0\r\n\r\n" % ctype).encode("utf-8")
            try:
                msg = email.message_from_bytes(header + raw, policy=email_policy.default)
            except Exception:
                self._send(400, json.dumps({"ok": False, "error": "解析失败"}))
                return
            filename = "alert.wav"
            payload = None
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                field = part.get_param("name", header="content-disposition") or ""
                body = part.get_payload(decode=True) or b""
                if field == "file":
                    filename = part.get_filename() or filename
                    payload = body
            sid, err = sound_util.save_upload(filename, payload)
            if err:
                self._send(400, json.dumps({"ok": False, "error": err}, ensure_ascii=False))
                return
            sound_util.save_selected(self.store, sid)
            self._send(200, json.dumps({"ok": True, "id": sid, "sounds": sound_util.list_sounds(self.store)}, ensure_ascii=False))
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}
        action = str(data.get("action") or "")
        sid = str(data.get("id") or "")
        if action == "select":
            sound_util.save_selected(self.store, sid)
        elif action == "play":
            sound_util.play_id(sid or None, self.store)
        elif action == "delete":
            sound_util.delete_custom(sid, self.store)
        self._send(200, json.dumps({"ok": True, "sounds": sound_util.list_sounds(self.store)}, ensure_ascii=False))

    def _handle_themes_post(self, raw):
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" in ctype.lower():
            self._upload_theme(raw)
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}
        if str(data.get("action") or "") == "delete":
            self._delete_theme(str(data.get("id") or ""))
            return
        self._send(400, json.dumps({"ok": False, "error": "需要上传文件或指定删除"}))

    def api_pet_packs(self):
        selected = pet_packs.normalize_selected(
            PET_PACKS_DIR, self.store.get_meta("pet_pack") or "default"
        )
        return {"selected": selected, "items": pet_packs.list_packs(PET_PACKS_DIR)}

    def _handle_pet_packs_post(self, raw):
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" in ctype.lower():
            self._upload_pet_pack(raw)
            return
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}
        action = str(data.get("action") or "")
        pack_id = str(data.get("id") or "")
        if action == "select":
            selected = pet_packs.normalize_selected(PET_PACKS_DIR, pack_id)
            if selected != pack_id:
                self._send(400, json.dumps({"ok": False, "error": "角色素材包不存在"}, ensure_ascii=False))
                return
            self.store.set_meta("pet_pack", selected)
            apply_pet_settings(pet_settings_from_store(self.store))
            self._send(200, json.dumps({"ok": True, "pets": self.api_pet_packs()}, ensure_ascii=False))
            return
        if action == "delete":
            try:
                deleted = pet_packs.delete_pack(PET_PACKS_DIR, pack_id)
            except Exception:
                deleted = False
            if not deleted:
                self._send(400, json.dumps({"ok": False, "error": "无法删除该素材包"}, ensure_ascii=False))
                return
            if (self.store.get_meta("pet_pack") or "default") == pack_id:
                self.store.set_meta("pet_pack", "default")
                apply_pet_settings(pet_settings_from_store(self.store))
            self._send(200, json.dumps({"ok": True, "pets": self.api_pet_packs()}, ensure_ascii=False))
            return
        self._send(400, json.dumps({"ok": False, "error": "需要上传、选择或删除角色"}, ensure_ascii=False))

    def _upload_pet_pack(self, raw):
        ctype = self.headers.get("Content-Type") or ""
        header = ("Content-Type: %s\r\nMIME-Version: 1.0\r\n\r\n" % ctype).encode("utf-8")
        try:
            msg = email.message_from_bytes(header + raw, policy=email_policy.default)
        except Exception:
            self._send(400, json.dumps({"ok": False, "error": "解析失败"}, ensure_ascii=False))
            return
        name = ""
        images = {}
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            field = part.get_param("name", header="content-disposition") or ""
            body = part.get_payload(decode=True) or b""
            if field == "name":
                try:
                    name = body.decode("utf-8").strip()
                except Exception:
                    pass
            elif field in pet_packs.KINDS and body:
                filename = part.get_filename() or ""
                if os.path.splitext(filename)[1].lower() != ".png":
                    self._send(400, json.dumps({"ok": False, "error": "角色立绘仅支持 PNG"}, ensure_ascii=False))
                    return
                images[field] = body
        info, err = pet_packs.save_pack(PET_PACKS_DIR, name, images)
        if err:
            self._send(400, json.dumps({"ok": False, "error": err}, ensure_ascii=False))
            return
        self.store.set_meta("pet_pack", info["id"])
        apply_pet_settings(pet_settings_from_store(self.store))
        self._send(200, json.dumps({"ok": True, "id": info["id"], "pets": self.api_pet_packs()}, ensure_ascii=False))

    def _delete_theme(self, tid):
        folder = theme_util.safe_theme_path(THEMES_DIR, tid)
        if not folder or not os.path.isdir(folder):
            self._send(400, json.dumps({"ok": False, "error": "主题不存在"}, ensure_ascii=False))
            return
        shutil.rmtree(folder, ignore_errors=True)
        if (self.store.get_meta("theme_id") or "") == tid:
            self.store.set_meta("theme_id", "")
        self._send(200, json.dumps({"ok": True, "themes": list_theme_packs()}, ensure_ascii=False))

    def _upload_theme(self, raw):
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in ctype.lower():
            self._send(400, json.dumps({"ok": False, "error": "需要 multipart"}))
            return
        header = ("Content-Type: %s\r\nMIME-Version: 1.0\r\n\r\n" % ctype).encode("utf-8")
        try:
            msg = email.message_from_bytes(header + raw, policy=email_policy.default)
        except Exception:
            self._send(400, json.dumps({"ok": False, "error": "解析失败"}))
            return
        display = ""
        overlay = 0.45
        payload = None
        ext = ""
        orig_name = ""
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            field = part.get_param("name", header="content-disposition") or ""
            body = part.get_payload(decode=True) or b""
            if field == "name":
                try:
                    display = body.decode("utf-8").strip()
                except Exception:
                    pass
            elif field == "overlay":
                try:
                    overlay = min(0.75, max(0.05, float(body.decode("utf-8"))))
                except Exception:
                    pass
            elif field == "file":
                orig = part.get_filename() or "wall.bin"
                orig_name = os.path.splitext(os.path.basename(orig))[0]
                ext = os.path.splitext(orig)[1].lower()
                payload = body
        if not display:
            display = orig_name or "自定义主题"
        if not payload or ext not in theme_util.ALLOWED_EXT:
            self._send(400, json.dumps({"ok": False, "error": "仅支持 jpg/png/gif/webp/mp4/webm"}))
            return
        if len(payload) > theme_util.MAX_UPLOAD:
            self._send(413, json.dumps({"ok": False, "error": "文件过大"}))
            return
        tid = "t" + uuid.uuid4().hex[:12]
        fname = "wall" + ext
        folder = theme_util.safe_theme_path(THEMES_DIR, tid)
        fpath = theme_util.safe_theme_path(THEMES_DIR, tid, fname)
        if not folder or not fpath:
            self._send(400, json.dumps({"ok": False}))
            return
        os.makedirs(folder, exist_ok=True)
        with open(fpath, "wb") as f:
            f.write(payload)
        cfg = {
            "name": display[:40],
            "background": fname,
            "overlay": overlay,
            "colors": {},
        }
        with open(os.path.join(folder, "theme.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        self.store.set_meta("theme_id", tid)
        self._send(200, json.dumps({"ok": True, "id": tid, "themes": list_theme_packs()}, ensure_ascii=False))

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._file(DASHBOARD_PATH, "text/html; charset=utf-8")
        elif path in ("/companion-chat", "/companion-chat.html"):
            self._file(COMPANION_CHAT_PATH, "text/html; charset=utf-8")
        elif path == "/echarts.min.js":
            self._file(ECHARTS_PATH, "application/javascript")
        elif path in ("/pet.html", "/pet", "/pet/"):
            self._file(PET_HTML, "text/html; charset=utf-8")
        elif path.startswith("/pet/sprites/"):
            self._pet_sprite(path)
        elif path == "/api/today":
            self._send(200, json.dumps(self.api_today(), ensure_ascii=False))
        elif path == "/api/apps":
            self._send(200, json.dumps(self.api_apps(), ensure_ascii=False))
        elif path == "/api/app-icon":
            self._app_icon()
        elif path == "/api/timeline":
            self._send(200, json.dumps(self.api_timeline(), ensure_ascii=False))
        elif path == "/api/week":
            self._send(200, json.dumps(self.api_week(), ensure_ascii=False))
        elif path == "/api/status":
            self._send(200, json.dumps(self.api_status(), ensure_ascii=False))
        elif path == "/api/clock":
            self._send(200, json.dumps(self.api_clock(), ensure_ascii=False))
        elif path == "/api/dashboard":
            self._send(200, json.dumps(self.api_dashboard(), ensure_ascii=False))
        elif path == "/api/rules":
            self._send(200, json.dumps(self.store.rules_editor(), ensure_ascii=False))
        elif path == "/api/themes":
            self._send(200, json.dumps(self.api_themes(), ensure_ascii=False))
        elif path == "/api/pets":
            self._send(200, json.dumps(self.api_pet_packs(), ensure_ascii=False))
        elif path == "/api/companion":
            self._send(200, json.dumps(self.api_companion(), ensure_ascii=False))
        elif path == "/api/companion/history":
            self._send(200, json.dumps({"items": companion_history_from_store(self.store)}, ensure_ascii=False))
        elif path == "/api/companion/templates":
            self._send(200, json.dumps({"ok": True, **companion_templates.public_items(companion_templates_from_store(self.store))}, ensure_ascii=False))
        elif path == "/api/companion/listen":
            self._send(200, json.dumps({"ok": True, "listen": speech_util.listen_status()}, ensure_ascii=False))
        elif path == "/api/companion/speaking":
            self._send(200, json.dumps({"ok": True, "speaking": speech_util.is_speaking()}, ensure_ascii=False))
        elif path == "/api/settings":
            self._send(200, json.dumps(self.api_settings(), ensure_ascii=False))
        elif path == "/api/ping":
            self._send(200, json.dumps({"ok": True}))
        elif path == "/api/pomodoro":
            self._send(200, json.dumps(pomodoro_util.snapshot(), ensure_ascii=False))
        elif path == "/api/sounds":
            self._send(200, json.dumps(sound_util.list_sounds(self.store), ensure_ascii=False))
        elif path.startswith("/api/sounds/file"):
            self._send_sound_file()
        elif path == "/app/icon.ico":
            ico = os.path.join(SCRIPT_DIR, "icon.ico")
            self._file(ico, "image/x-icon")
        elif path == "/app/icon.png":
            self._file(os.path.join(SCRIPT_DIR, "icon.png"), "image/png")
        elif path.startswith("/themes/"):
            self._theme_file(path)
        elif path.startswith("/petpacks/"):
            parts = [p for p in path.split("/") if p]
            fpath = None
            if len(parts) == 3:
                fpath = pet_packs.safe_pack_file(PET_PACKS_DIR, parts[1], parts[2])
            if not fpath or not os.path.isfile(fpath) or parts[2] == "pack.json":
                self._send(404, b"not found")
            else:
                self._file(fpath, "image/png")
        else:
            self._send(404, b"not found")

    def log_message(self, *a):
        pass

    def _live_delta(self):
        if not (self.tracker and self.tracker.cur):
            return 0.0, None, None
        el = time.time() - self.tracker.cur["start"]
        return max(0.0, el), self.tracker.cur["state"], self.tracker.cur.get("app")

    def _closed_today(self):
        today = date_str(time.time())
        row = self.store.read(
            "SELECT active_seconds, away_seconds, system_seconds FROM daily_stats WHERE date=?",
            (today,),
        )
        active = row[0][0] if row else 0.0
        away = row[0][1] if row else 0.0
        system = row[0][2] if row else 0.0
        return today, float(active or 0), float(away or 0), float(system or 0)

    def api_clock(self):
        now = time.time()
        today, active_c, away_c, system_c = self._closed_today()
        cur = self.tracker.cur if self.tracker else None
        live_start = float(cur["start"]) if cur else None
        live_state = (cur.get("state") if cur else None) or "active"
        live_app = cur.get("app") if cur else None
        live_title = cur.get("title") if cur else None
        live_cat = None
        if cur and live_state == "active":
            live_cat = cur.get("category")
        app_closed = 0.0
        if live_app:
            rows = self.store.read(
                "SELECT active_seconds FROM app_daily_stats WHERE date=? AND app_name=?",
                (today, live_app),
            )
            app_closed = float(rows[0][0]) if rows else 0.0
        cat_closed = 0.0
        if live_cat:
            rows = self.store.read(
                "SELECT active_seconds FROM category_daily_stats WHERE date=? AND category=?",
                (today, live_cat),
            )
            cat_closed = float(rows[0][0]) if rows else 0.0
        idle = get_idle_seconds()
        return {
            "server_ts": now,
            "live_start": live_start,
            "live_state": live_state,
            "live_app": live_app,
            "live_title": live_title,
            "live_category": live_cat,
            "active_closed": active_c,
            "away_closed": away_c,
            "system_closed": system_c,
            "app_closed": app_closed,
            "cat_closed": cat_closed,
            "idle_seconds": idle,
            "away_in_seconds": max(0.0, AWAY_THRESHOLD - idle) if live_state == "active" else 0.0,
        }

    def api_status(self):
        el, state, app = self._live_delta()
        title = None
        if self.tracker and self.tracker.cur:
            title = self.tracker.cur.get("title")
        idle = get_idle_seconds()
        remain = max(0.0, AWAY_THRESHOLD - idle) if state == "active" else 0.0
        return {
            "state": state or "active",
            "app": app,
            "title": title,
            "open_seconds": el,
            "idle_seconds": idle,
            "away_in_seconds": remain,
            "category": None if state != "active" else (
                self.tracker.cur.get("category") if self.tracker and self.tracker.cur else None
            ),
        }

    def _today_segments(self):
        day_start = today_start_ts()
        rows = self.store.read(
            "SELECT start_ts, end_ts, app_name, state, window_title, category FROM segments WHERE start_ts < ? AND end_ts > ? ORDER BY start_ts",
            (day_start + 86400, day_start),
        )
        segs = []
        for r in rows:
            segs.append(
                {
                    "start": r[0],
                    "end": r[1],
                    "app": r[2],
                    "state": r[3],
                    "title": r[4],
                    "category": r[5],
                }
            )
        if self.tracker and self.tracker.cur:
            segs.append(
                {
                    "start": self.tracker.cur["start"],
                    "end": time.time(),
                    "app": self.tracker.cur["app"],
                    "state": self.tracker.cur["state"],
                    "title": self.tracker.cur.get("title"),
                    "category": self.tracker.cur.get("category"),
                    "live": True,
                }
            )
        return day_start, segs

    def api_today(self):
        today = date_str(time.time())
        row = self.store.read(
            "SELECT active_seconds, away_seconds, system_seconds FROM daily_stats WHERE date=?",
            (today,),
        )
        active = row[0][0] if row else 0.0
        away = row[0][1] if row else 0.0
        system = row[0][2] if row else 0.0
        el, state, _app = self._live_delta()
        if state == "active":
            active += el
            system += el
        elif state == "away":
            away += el
            system += el
        return {
            "date": today,
            "active": active,
            "away": away,
            "system": system,
            "active_fmt": fmt_hms(active),
            "away_fmt": fmt_hms(away),
            "system_fmt": fmt_hms(system),
            "state": state or "active",
        }

    def api_apps(self):
        today = date_str(time.time())
        rows = self.store.read(
            "SELECT app_name, active_seconds FROM app_daily_stats WHERE date=?", (today,)
        )
        data = {r[0]: r[1] for r in rows}
        el, state, app = self._live_delta()
        if state == "active" and app and el > 0 and self.store.should_credit_app(app, None):
            data[app] = data.get(app, 0) + el
        items = [
            {"name": k, "value": round(v)}
            for k, v in data.items()
            if k and self.store.should_credit_app(k, None)
        ]
        items.sort(key=lambda x: x["value"], reverse=True)
        return {"date": today, "items": items}

    def api_timeline(self):
        day_start, segs = self._today_segments()
        return {"day_start": day_start, "segments": segs}

    def api_dashboard(self):
        today = self.api_today()
        status = self.api_status()
        apps = self.api_apps()
        week = self.api_week()
        day_start, segs = self._today_segments()
        hourly = {
            "active": [0.0] * 24,
            "away": [0.0] * 24,
            "sleep": [0.0] * 24,
        }
        sleep = 0.0
        first_active = None
        last_active = None
        switches = 0
        prev_app = object()
        for seg in segs:
            credits = hour_credits(seg["start"], seg["end"], day_start)
            key = seg["state"] if seg["state"] in hourly else None
            if key:
                for i, v in enumerate(credits):
                    hourly[key][i] += v
            if seg["state"] == "sleep":
                sleep += max(0.0, seg["end"] - seg["start"])
            if seg["state"] == "active":
                if first_active is None:
                    first_active = seg["start"]
                last_active = seg["end"]
                if seg.get("app") != prev_app:
                    if prev_app is not object():
                        switches += 1
                    prev_app = seg.get("app")
        total_app = sum(x["value"] for x in apps["items"]) or 1
        ranked = []
        for i, item in enumerate(apps["items"]):
            ranked.append(
                {
                    "rank": i + 1,
                    "name": item["name"],
                    "seconds": item["value"],
                    "fmt": fmt_hms(item["value"]),
                    "percent": round(100.0 * item["value"] / total_app, 1),
                }
            )
        sessions = []
        for seg in reversed(segs[-40:]):
            dur = max(0.0, seg["end"] - seg["start"])
            sessions.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "app": seg.get("app"),
                    "title": seg.get("title"),
                    "category": seg.get("category"),
                    "state": seg["state"],
                    "seconds": round(dur),
                    "fmt": fmt_hms(dur),
                    "live": bool(seg.get("live")),
                }
            )
        active = today["active"]
        system = today["system"] or 1
        clk = self.api_clock()
        clk["sleep_closed"] = sleep
        cats = self.api_categories()
        cat_secs = {x["name"]: x["seconds"] for x in cats}
        ignore_apps = self.store.ignore_config()["apps"]
        return {
            "today": today,
            "status": status,
            "hourly": hourly,
            "week": week["items"],
            "apps": ranked,
            "timeline": {"day_start": day_start, "segments": segs},
            "sessions": sessions,
            "sleep_seconds": sleep,
            "sleep_fmt": fmt_hms(sleep),
            "focus_ratio": round(100.0 * active / system, 1) if today["system"] else 0,
            "app_switches": switches,
            "first_active": first_active,
            "last_active": last_active,
            "top_app": ranked[0] if ranked else None,
            "categories": cats,
            "category_breakdown": build_category_breakdown(segs, ignore_apps=ignore_apps),
            "clock": clk,
            "goals_progress": goals_util.goals_progress(today["active"], cat_secs, self.store.daily_goals()),
        }

    def api_categories(self):
        today = date_str(time.time())
        rows = self.store.read(
            "SELECT category, active_seconds FROM category_daily_stats WHERE date=?", (today,)
        )
        data = {name: 0.0 for name in classify_mod.CATEGORIES}
        for r in rows:
            if r[0]:
                data[r[0]] = data.get(r[0], 0.0) + float(r[1] or 0)
        el, state, app = self._live_delta()
        cat = None
        if self.tracker and self.tracker.cur:
            cat = self.tracker.cur.get("category")
        if state == "active" and cat and el > 0 and self.store.should_credit_app(app, None):
            data[cat] = data.get(cat, 0.0) + el
        total = sum(data.values()) or 1
        order = {name: i for i, name in enumerate(classify_mod.CATEGORIES)}
        items = []
        for name, sec in sorted(data.items(), key=lambda x: (-x[1], order.get(x[0], 99))):
            items.append(
                {
                    "name": name,
                    "seconds": round(sec),
                    "fmt": fmt_hms(sec),
                    "percent": round(100.0 * sec / total, 1),
                }
            )
        return items

    def api_themes(self):
        return {"items": list_theme_packs()}

    def api_settings(self):
        tid = self.store.get_meta("theme_id") or ""
        packs = {p["id"]: p for p in list_theme_packs()}
        pack = packs.get(tid)
        overlay = self.store.get_meta("overlay")
        if overlay is None:
            overlay = 0.28 if pack else 0.22
        try:
            overlay = float(overlay)
        except Exception:
            overlay = 0.28
        overlay = min(0.75, max(0.05, overlay))
        bg = None
        if pack and pack.get("background") and _theme_media_exists(pack["id"], pack["background"]):
            bg = "/themes/%s/%s" % (pack["id"], pack["background"])
        result = {
            "palette": self.store.get_meta("palette") or "midnight",
            "theme_id": tid,
            "overlay": overlay,
            "background": bg,
            "themes": list_theme_packs(),
            "show_pet": (self.store.get_meta("show_pet") or "1") != "0",
            "ignore_apps": self.store.ignore_config()["apps"],
            "ignore_min_seconds": self.store.ignore_config()["min_seconds"],
            "daily_goals": self.store.daily_goals(),
        }
        result.update(pet_settings_from_store(self.store))
        result["companion_behavior"] = companion.normalize_behavior(
            self.store.get_meta("companion_behavior") or "companion"
        )
        ai = companion_ai_settings_from_store(self.store)
        ai["usage"] = companion_ai_usage_from_store(self.store, ai["interaction_level"])
        result["ai_companion"] = ai
        return result

    def api_companion(self):
        behavior = companion.normalize_behavior(self.store.get_meta("companion_behavior") or "companion")
        return companion.build_snapshot(self.api_dashboard(), pomodoro_util.snapshot(), behavior)

    def api_companion_chat(self, data):
        message = companion_ai.clean_text((data or {}).get("message"), companion_ai.MAX_MESSAGE)
        dashboard = self.api_dashboard()
        behavior = companion.normalize_behavior(self.store.get_meta("companion_behavior") or "companion")
        snapshot = companion.build_snapshot(dashboard, pomodoro_util.snapshot(), behavior)
        settings = companion_ai_settings_from_store(self.store, include_secret=True)
        if settings.get("share_app"):
            snapshot["current_app"] = (dashboard.get("status") or {}).get("app") or ""
        history = companion_history_from_store(self.store)
        usage = companion_ai_usage_from_store(self.store, settings["interaction_level"])
        capped = settings.get("enabled") and settings.get("provider") != "off" and usage["requests"] >= usage["request_limit"]
        generate_settings = dict(settings)
        if capped:
            generate_settings["enabled"] = False
        reply = companion_ai.generate(generate_settings, snapshot, message, history, snapshot.get("recommendation"), companion_templates_from_store(self.store))
        if capped:
            reply["error"] = "今日模型额度已用完，已切换本地回应"
        elif reply.get("source") == "model":
            usage = record_companion_ai_usage(self.store, settings["interaction_level"], message, reply.get("reply"))
        history.extend([
            {"role": "user", "content": message or "给我一句陪伴。"},
            {"role": "assistant", "content": reply["reply"]},
        ])
        history = history[-companion_ai.MAX_HISTORY:]
        self.store.set_meta("ai_history", json.dumps(history, ensure_ascii=False))
        action = reply.get("action") if reply.get("action") in companion.ACTION_NAMES else "hello"
        snapshot["reply"] = reply["reply"]
        apply_companion_action(action, snapshot)
        # 对话是用户主动触发的，即使未开启主动朗读也应完整说出回应。
        speech_util.speak_stream_async(reply["reply"], True, settings["voice_rate"], settings["voice_preset"])
        public_snapshot = dict(snapshot)
        public_snapshot.pop("current_app", None)
        return {
            "ok": True,
            "reply": reply["reply"],
            "action": action,
            "source": reply["source"],
            "fallback_reason": reply.get("error") or "",
            "usage": usage,
            "companion": public_snapshot,
            "history": history,
        }

    def api_companion_templates(self, data):
        """只允许管理用户自定义的离线模板；内置模板始终保留作安全兜底。"""
        custom = companion_templates_from_store(self.store)
        action = str((data or {}).get("action") or "")
        if action == "create":
            item = companion_templates.normalize_item((data or {}).get("item"))
            if not item:
                return {"ok": False, "error": "请填写回复内容"}
            if len(custom) >= companion_templates.MAX_CUSTOM:
                return {"ok": False, "error": "最多可添加 %d 条自定义模板" % companion_templates.MAX_CUSTOM}
            custom.append(item)
        elif action == "update":
            item = companion_templates.normalize_item((data or {}).get("item"))
            if not item:
                return {"ok": False, "error": "请填写回复内容"}
            for index, old in enumerate(custom):
                if old["id"] == item["id"]:
                    custom[index] = item
                    break
            else:
                return {"ok": False, "error": "未找到该自定义模板"}
        elif action == "delete":
            target = str((data or {}).get("id") or "")
            custom = [item for item in custom if item["id"] != target]
        else:
            return {"ok": False, "error": "未知模板操作"}
        self.store.set_meta("offline_reply_templates", json.dumps(custom, ensure_ascii=False))
        return {"ok": True, **companion_templates.public_items(custom)}

    def api_week(self):
        today = datetime.date.today()
        start = (today - datetime.timedelta(days=6)).strftime("%Y-%m-%d")
        rows = self.store.read(
            "SELECT date, active_seconds, away_seconds, system_seconds FROM daily_stats WHERE date >= ? ORDER BY date",
            (start,),
        )
        by_date = {r[0]: r for r in rows}
        out = []
        el, state, _app = self._live_delta()
        for i in range(6, -1, -1):
            d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            r = by_date.get(d)
            active = r[1] if r else 0.0
            away = r[2] if r else 0.0
            system = r[3] if r else 0.0
            if d == date_str(time.time()):
                if state == "active":
                    active += el
                    system += el
                elif state == "away":
                    away += el
                    system += el
            out.append(
                {"date": d, "active": round(active), "away": round(away), "system": round(system)}
            )
        return {"items": out}


def find_port(p):
    while True:
        try:
            s = socketserver.socket.socket(socketserver.socket.AF_INET, socketserver.socket.SOCK_STREAM)
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            p += 1


def write_status_files(url):
    try:
        with open(URL_PATH, "w", encoding="utf-8") as f:
            f.write(url)
        with open(PID_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log.warning("写状态文件失败: %s", e)


def clear_status_files():
    for path in (PID_PATH,):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


_backend = {
    "httpd": None,
    "stop": None,
    "tracker": None,
    "lock_fp": None,
    "url": None,
    "shutting": False,
}


def try_instance_lock():
    os.makedirs(DATA_DIR, exist_ok=True)
    fp = open(LOCK_PATH, "a+b")
    try:
        if fp.tell() == 0:
            fp.write(b"\0")
            fp.flush()
        fp.seek(0)
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fp.close()
        return None
    return fp


def maybe_upgrade_glass(store):
    if store.get_meta("glass_ui") == "1":
        return
    ov = store.get_meta("overlay")
    if ov is None or ov in ("0.45", "0.5", "0.50", "0.55"):
        store.set_meta("overlay", "0.28")
    store.set_meta("glass_ui", "1")


def maybe_upgrade_classify(store, tracker=None):
    if store.get_meta("classify_rev") == classify_mod.CLASSIFY_REV:
        return
    today = datetime.date.today()
    for i in range(7):
        d = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        store.reclassify_day(d)
    store.set_meta("classify_rev", classify_mod.CLASSIFY_REV)
    if tracker and tracker.cur and tracker.cur.get("state") == "active":
        tracker.cur["category"] = classify_mod.classify(
            tracker.cur.get("app"), tracker.cur.get("title"), store.rules()
        )
    log.info("已按新规则重算近 7 天分类")


def start_backend(serve_in_thread=True):
    if _backend["httpd"] is not None:
        return _backend["url"]
    if not PLATFORM_OK:
        return None
    lock_fp = try_instance_lock()
    if lock_fp is None:
        return None
    store = Storage(DB_PATH)
    tracker = Tracker(store)
    maybe_upgrade_classify(store, tracker)
    maybe_upgrade_glass(store)
    try:
        sound_util.ensure_defaults()
    except Exception:
        log.warning("生成默认提醒音失败", exc_info=True)
    stop = threading.Event()
    threading.Thread(target=collector_loop, args=(tracker, stop), daemon=True).start()
    Handler.tracker = tracker
    Handler.store = store
    port = find_port(PORT)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d" % port
    _backend.update({
        "httpd": httpd,
        "stop": stop,
        "tracker": tracker,
        "lock_fp": lock_fp,
        "url": url,
        "shutting": False,
    })
    write_status_files(url)
    log.info("面板服务启动: %s", url)
    if serve_in_thread:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return url


def shutdown_backend():
    if _backend["shutting"]:
        return
    _backend["shutting"] = True
    stop = _backend.get("stop")
    tracker = _backend.get("tracker")
    httpd = _backend.get("httpd")
    if stop:
        stop.set()
    if tracker:
        try:
            tracker.finalize()
        except Exception:
            pass
    if httpd:
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
    lock_fp = _backend.get("lock_fp")
    if lock_fp:
        try:
            lock_fp.close()
        except Exception:
            pass
    clear_status_files()
    _backend["httpd"] = None
    log.info("程序退出")


def request_shutdown():
    def _go():
        time.sleep(0.15)
        shutdown_backend()
        os._exit(0)
    threading.Thread(target=_go, daemon=True).start()


def current_url():
    return _backend.get("url")


def main():
    if not PLATFORM_OK:
        print("当前不是 Windows 系统，无法采集数据。")
        return
    ensure_desktop_shortcut()
    url = start_backend(serve_in_thread=False)
    if not url:
        print("已经在运行。")
        return
    atexit.register(shutdown_backend)
    try:
        _backend["httpd"].serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_backend()


if __name__ == "__main__":
    main()
