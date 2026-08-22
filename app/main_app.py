# -*- coding: utf-8 -*-
"""Ticko - 桌面时间记录窗口与系统托盘。"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

# Ticko is distributed as a self-contained Windows app; keep runtime caches
# out of the application folder.
sys.dont_write_bytecode = True

from ctypes import wintypes

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import app as usage
import pet_engine
import pet_geom
import pet_view

APP_TITLE = "Ticko"
PET_TITLE = "TickoPet"
APP_ID = "Ticko.Desktop"
MUTEX_NAME = "Local\\TickoSingleInstance"
ICON_PATH = os.path.join(SCRIPT_DIR, "icon.ico")
ICON_PNG = os.path.join(SCRIPT_DIR, "icon.png")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT
]
user32.LoadImageW.restype = wintypes.HANDLE
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.MessageBoxW.restype = ctypes.c_int

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetLastError.restype = wintypes.DWORD
kernel32.SetLastError.argtypes = [wintypes.DWORD]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
try:
    user32.GetDpiForSystem.restype = ctypes.c_uint
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = ctypes.c_uint
except Exception:
    pass
SW_RESTORE = 9
SW_SHOW = 5
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
SPI_GETWORKAREA = 0x0030
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
VK_LBUTTON = 0x01
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
ERROR_ALREADY_EXISTS = 183
MB_ICONERROR = 0x10

_state = {
    "window": None, "pet": None, "tray": None, "exiting": False, "engine": None,
    "pet_save_ts": 0, "pet_run": False, "pet_hwnd": None, "drag_alive": False,
    "drag_moved": False, "js_busy": False, "js_pending": None, "work_ts": 0, "chat_window": None,
}


def set_app_id():
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def alert(msg):
    user32.MessageBoxW(None, str(msg), APP_TITLE, MB_ICONERROR)


_webview_lock = threading.Lock()


def _call_webview(fn):
    """pywebview 的 show/evaluate_js 不能在桌宠 WinForms 线程里同步调用，否则会卡死。"""
    def _run():
        with _webview_lock:
            try:
                fn()
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True, name="webview-call").start()


def _show_dashboard_hwnd():
    hwnd = user32.FindWindowW(None, APP_TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, SW_SHOW)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    # 桌宠属于桌面层；主面板打开时暂时隐藏，避免遮挡数据和控件。
    view = _state.get("pet_view")
    if view:
        try:
            view.hide()
        except Exception:
            pass
    return bool(hwnd)


def bring_to_front():
    shown = _show_dashboard_hwnd()
    w = _state.get("window")
    if not w:
        return shown

    def _show():
        try:
            w.show()
            w.restore()
        except Exception:
            pass

    _call_webview(_show)
    return True


def open_dashboard_page(hash_name):
    page = str(hash_name or "#overview")
    if not page.startswith("#"):
        page = "#" + page
    _show_dashboard_hwnd()

    def _go():
        w = _state.get("window")
        if not w:
            return
        try:
            w.show()
            w.restore()
        except Exception:
            pass
        script = (
            "try{location.hash=%s;if(typeof showPage==='function')showPage();}catch(e){}"
            % json.dumps(page)
        )
        try:
            w.evaluate_js(script)
        except Exception:
            try:
                w.run_js(script)
            except Exception:
                pass

    _call_webview(_go)


def open_companion_chat_window():
    """打开贴近桌宠的小型独立对话窗，不占用主面板。"""
    def _open():
        existing = _state.get("chat_window")
        if existing:
            try:
                existing.show()
                existing.restore()
                return
            except Exception:
                _state["chat_window"] = None
        try:
            import webview
            base_url = usage._backend.get("url")
            if not base_url:
                return
            px, py = 32, 160
            pet = _state.get("pet_view")
            if pet and getattr(pet, "form", None):
                try:
                    px = max(16, int(pet.form.Location.X) - 440)
                    py = max(16, int(pet.form.Location.Y) - 110)
                except Exception:
                    pass
            chat = webview.create_window("和 Ticko 聊聊", base_url.rstrip("/") + "/companion-chat", width=420, height=560, min_size=(360, 420), x=px, y=py, text_select=True)
            _state["chat_window"] = chat
            try:
                chat.events.closed += lambda: _state.__setitem__("chat_window", None)
            except Exception:
                pass
        except Exception as exc:
            usage.log.warning("打开独立对话窗失败：%s", exc)
    _call_webview(_open)


def close_companion_chat_window():
    """结束一次语音对话并隐藏小窗，桌宠和主面板继续运行。"""
    try:
        import speech_util
        speech_util.stop_listening()
    except Exception:
        pass
    def _close():
        chat = _state.get("chat_window")
        if not chat:
            return
        try:
            chat.destroy()
        except Exception:
            pass
        _state["chat_window"] = None
    _call_webview(_close)


def acquire_mutex():
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    err = kernel32.GetLastError()
    if not handle:
        return None, False
    return handle, err == ERROR_ALREADY_EXISTS


def pid_alive(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = wintypes.DWORD()
    ok = kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    kernel32.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


def stop_stale():
    pid = None
    try:
        with open(usage.PID_PATH, "r", encoding="utf-8") as f:
            pid = int((f.read() or "0").strip() or "0")
    except Exception:
        pid = None
    if not pid or pid == os.getpid() or not pid_alive(pid):
        return
    url = ""
    try:
        with open(usage.URL_PATH, "r", encoding="utf-8") as f:
            url = (f.read() or "").strip()
    except Exception:
        pass
    if url:
        try:
            req = urllib.request.Request(url.rstrip("/") + "/api/shutdown", data=b"{}", method="POST")
            urllib.request.urlopen(req, timeout=2).read()
            time.sleep(0.6)
        except Exception:
            pass
    if pid_alive(pid):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        time.sleep(0.3)


def wait_ready(url, seconds=15):
    ping = url.rstrip("/") + "/api/ping"
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(ping, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def process_is_dpi_aware():
    try:
        val = ctypes.c_int(-1)
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(val))
        return val.value >= 1
    except Exception:
        return False


def dpi_scale(hwnd=None):
    try:
        if hwnd:
            dpi = int(user32.GetDpiForWindow(hwnd) or 0)
        else:
            dpi = int(user32.GetDpiForSystem() or 0)
        if dpi:
            return max(float(dpi) / 96.0, 1.0)
    except Exception:
        pass
    return 1.0


def logical_work_area(hwnd=None):
    rc = wintypes.RECT()
    if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rc), 0):
        rc.left = 0
        rc.top = 0
        rc.right = user32.GetSystemMetrics(0)
        rc.bottom = user32.GetSystemMetrics(1)
    scale = dpi_scale(hwnd)
    if process_is_dpi_aware() and scale > 1.01:
        return (
            int(round(rc.left / scale)),
            int(round(rc.top / scale)),
            int(round((rc.right - rc.left) / scale)),
            int(round((rc.bottom - rc.top) / scale)),
        )
    return (int(rc.left), int(rc.top), int(rc.right - rc.left), int(rc.bottom - rc.top))


def apply_pet_tool_style():
    hwnd = user32.FindWindowW(None, PET_TITLE)
    if not hwnd:
        return
    style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0)
    style = (style | WS_EX_TOOLWINDOW | WS_EX_LAYERED) & ~WS_EX_APPWINDOW
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED | SWP_NOACTIVATE,
    )


def screen_to_logical(sx, sy, hwnd=None):
    scale = dpi_scale(hwnd)
    if process_is_dpi_aware() and scale > 1.01:
        return int(round(float(sx) / scale)), int(round(float(sy) / scale))
    return int(sx), int(sy)


def cursor_logical(hwnd=None):
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return None
    return screen_to_logical(pt.x, pt.y, hwnd)


def live_away():
    try:
        tr = usage._backend.get("tracker")
        return bool(tr and tr.cur and tr.cur.get("state") == "away")
    except Exception:
        return False


def meta_get(key, default=""):
    try:
        store = usage.Handler.store
        if store:
            val = store.get_meta(key)
            if val is not None:
                return val
    except Exception:
        pass
    return default


def meta_set(key, value):
    try:
        if usage.Handler.store:
            usage.Handler.store.set_meta(key, str(value))
    except Exception:
        pass


def load_pet_size():
    if meta_get("pet_size_v", "") != "2":
        meta_set("pet_size_v", "2")
        meta_set("pet_size", pet_geom.DEFAULT_SIZE)
        return pet_geom.DEFAULT_SIZE
    lab = meta_get("pet_size", pet_geom.DEFAULT_SIZE)
    return lab if lab in pet_geom.SIZE_H else pet_geom.DEFAULT_SIZE


def load_pet_mode():
    mode = meta_get("pet_mode", "wander")
    return mode if mode in pet_engine.MODES else "wander"


def load_pet_speech():
    level = meta_get("pet_speech", "normal")
    return level if level in pet_engine.SPEECH_LEVELS else "normal"


def load_pet_lines():
    return pet_engine.normalize_custom_lines(meta_get("pet_lines", ""))


def load_interaction_level():
    level = meta_get("ai_interaction_level", "medium")
    return level if level in pet_engine.INTERACTION_LEVELS else "medium"


def load_pet_pack():
    return usage.pet_packs.normalize_selected(
        usage.PET_PACKS_DIR, meta_get("pet_pack", "default")
    )


def pet_sprite_dir(pack_id):
    if not pack_id or pack_id == "default":
        return None
    folder = usage.pet_packs.safe_pack_dir(usage.PET_PACKS_DIR, pack_id)
    return folder if folder and os.path.isdir(folder) else None


def apply_pet_js(payload):
    p = _state.get("pet")
    if not p or not payload:
        return
    script = "window.__petApply && window.__petApply(%s)" % json.dumps(payload, ensure_ascii=False)
    try:
        p.run_js(script)
    except Exception:
        try:
            p.evaluate_js(script)
        except Exception:
            pass


def pose_payload(eng, extra=None):
    walking = eng.target is not None and not eng.dragging and not eng.away
    data = {
        "dir": eng.dir,
        "facing": eng.facing,
        "walking": walking,
        "away": eng.away,
        "mode": eng.mode,
        "size": eng.size_label,
        "sprite_h": eng.sprite_h,
    }
    if extra:
        data.update(extra)
    return data


def ensure_engine(x=None, y=None):
    eng = _state.get("engine")
    if eng:
        return eng
    size_label = load_pet_size()
    w, h = pet_geom.window_size(pet_geom.SIZE_H[size_label])
    hwnd = user32.FindWindowW(None, PET_TITLE)
    work = logical_work_area(hwnd)
    if x is None or y is None:
        x, y = pet_geom.default_pet_pos_from_work(work, w, h)
    eng = pet_engine.PetEngine(x, y, w, h, work, size_label=size_label)
    eng.set_mode(load_pet_mode())
    eng.set_speech_level(load_pet_speech())
    eng.set_interaction_level(load_interaction_level())
    eng.set_custom_lines(load_pet_lines())
    eng.set_pet_pack(load_pet_pack())
    _state["engine"] = eng
    return eng


def pet_hwnd():
    h = _state.get("pet_hwnd")
    if h and user32.IsWindow(h):
        return h
    h = user32.FindWindowW(None, PET_TITLE)
    _state["pet_hwnd"] = h
    return h


def logical_to_physical(x, y, hwnd=None):
    scale = dpi_scale(hwnd)
    if process_is_dpi_aware() and scale > 1.01:
        return int(round(float(x) * scale)), int(round(float(y) * scale))
    return int(x), int(y)


def physical_to_logical(x, y, hwnd=None):
    scale = dpi_scale(hwnd)
    if process_is_dpi_aware() and scale > 1.01:
        return int(round(float(x) / scale)), int(round(float(y) / scale))
    return int(x), int(y)


def move_pet_native(x, y):
    hwnd = pet_hwnd()
    if not hwnd:
        return
    px, py = logical_to_physical(x, y, hwnd)
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        px,
        py,
        0,
        0,
        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
    )


def sync_engine_from_window():
    eng = _state.get("engine")
    hwnd = pet_hwnd()
    if not eng or not hwnd:
        return
    rc = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return
    lx, ly = physical_to_logical(rc.left, rc.top, hwnd)
    eng.x, eng.y = float(lx), float(ly)


def push_pet_js_async(payload):
    if not payload:
        return
    if _state.get("js_busy"):
        _state["js_pending"] = payload
        return
    _state["js_busy"] = True

    def _go():
        try:
            apply_pet_js(payload)
            pending = _state.pop("js_pending", None)
            if pending:
                apply_pet_js(pending)
        except Exception:
            pass
        finally:
            _state["js_busy"] = False

    threading.Thread(target=_go, daemon=True).start()


def _native_drag_loop():
    hwnd = pet_hwnd()
    eng = _state.get("engine")
    try:
        if not hwnd:
            return
        rc = wintypes.RECT()
        pt = wintypes.POINT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        user32.GetCursorPos(ctypes.byref(pt))
        ox, oy = pt.x - rc.left, pt.y - rc.top
        start = (pt.x, pt.y)
        lastx = pt.x
        last_js = 0.0
        flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        while (
            not _state.get("exiting")
            and _state.get("drag_alive")
            and (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        ):
            user32.GetCursorPos(ctypes.byref(pt))
            if abs(pt.x - start[0]) + abs(pt.y - start[1]) > 6:
                _state["drag_moved"] = True
                user32.SetWindowPos(hwnd, HWND_TOPMOST, pt.x - ox, pt.y - oy, 0, 0, flags)
                dx = pt.x - lastx
                if eng and abs(dx) > 10:
                    eng._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
                    lastx = pt.x
                    now = time.time()
                    if now - last_js > 0.06:
                        last_js = now
                        push_pet_js_async(pose_payload(eng))
            time.sleep(0.008)
        sync_engine_from_window()
    finally:
        _state["drag_alive"] = False


def start_native_drag():
    if _state.get("drag_alive"):
        return
    eng = ensure_engine()
    eng.on_drag_start()
    _state["drag_moved"] = False
    _state["drag_alive"] = True
    threading.Thread(target=_native_drag_loop, daemon=True, name="pet-drag").start()


def _start_auto_companion_reply(store, dashboard, behavior, trigger):
    if _state.get("ai_companion_pending"):
        return
    _state["ai_companion_pending"] = True

    def _worker():
        try:
            import pomodoro_util
            result = usage.maybe_companion_auto_reply(store, dashboard, pomodoro_util.snapshot(), behavior, trigger)
            if result:
                usage.apply_companion_action(result["action"], result["snapshot"])
        except Exception:
            usage.log.warning("智能伙伴主动回应失败", exc_info=True)
        finally:
            _state["ai_companion_pending"] = False

    threading.Thread(target=_worker, daemon=True, name="companion-reply").start()


def _pet_runtime_tick():
    eng = _state.get("engine")
    if not eng or eng.dragging or not pet_enabled():
        return
    hwnd = pet_hwnd()
    now = time.time()
    if now - float(_state.get("work_ts") or 0) > 1:
        _state["work_ts"] = now
        eng.work = logical_work_area(hwnd)
    eng.away = live_away()
    behavior = meta_get("companion_behavior", "companion")
    eng.set_interaction_level(load_interaction_level())
    eng.quiet = behavior in ("focus", "quiet")
    interaction_level = eng.interaction_level
    poll_interval = {"light": 45, "medium": 20, "heavy": 8}[interaction_level]
    # 数据驱动的反应只在状态切换时发生，并以较低频率读取统计，避免打扰和
    # 避免在每一帧重复计算完整看板。
    if now - float(_state.get("companion_poll_ts") or 0) >= poll_interval:
        _state["companion_poll_ts"] = now
        try:
            store = getattr(usage.Handler, "store", None)
            if store:
                dashboard = usage.Handler.__new__(usage.Handler).api_dashboard()
                snap = usage.companion.build_snapshot(
                    dashboard,
                    __import__("pomodoro_util").snapshot(),
                    behavior,
                )
                state = snap.get("state")
                prior = _state.get("companion_state")
                _state["companion_state"] = state
                if state != prior and state == "celebrate":
                    eng.jump_t = 0.55 if interaction_level == "light" else 1.0
                    if interaction_level != "light":
                        eng.action, eng.action_t = "sway", 1.0
                    eng.say("今天的目标完成了，真棒！")
                elif state != prior and state == "rest" and behavior != "quiet" and interaction_level != "light":
                    eng.action, eng.action_t = "stretch", 1.0
                    eng.say("回来后我们再继续。")
                elif state != prior and state == "steady" and interaction_level == "heavy" and behavior != "quiet":
                    eng.action, eng.action_t = "sway", 0.65
                if state != prior:
                    _start_auto_companion_reply(store, dashboard, behavior, state)
        except Exception:
            pass
    cursor = cursor_logical(hwnd) if eng.mode == "follow" else None
    events = eng.tick(cursor=cursor)
    if events.get("pos"):
        move_pet_native(eng.x, eng.y)
        if now - float(_state.get("pet_save_ts") or 0) > 12:
            _state["pet_save_ts"] = now
            meta_set("pet_x", int(eng.x))
            meta_set("pet_y", int(eng.y))
    extra = {}
    if events.get("jump"):
        extra["jump"] = events["jump"]
    if events.get("action"):
        extra["action"] = events["action"]
    if events.get("say"):
        extra["say"] = events["say"]
        extra["inner"] = events.get("inner", False)
    if extra or events.get("pose"):
        push_pet_js_async(pose_payload(eng, extra))


def start_pet_runtime():
    if _state.get("pet_run"):
        return
    _state["pet_run"] = True

    def loop():
        while _state.get("pet_run") and not _state.get("exiting"):
            t0 = time.perf_counter()
            try:
                _pet_runtime_tick()
            except Exception:
                pass
            time.sleep(max(0.0, 0.02 - (time.perf_counter() - t0)))

    threading.Thread(target=loop, daemon=True, name="pet-runtime").start()


def log_pet_geom():
    hwnd = user32.FindWindowW(None, PET_TITLE)
    if not hwnd:
        usage.log.warning("桌宠窗口未找到")
        return False
    rc = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    vis = bool(user32.IsWindowVisible(hwnd))
    w = rc.right - rc.left
    h = rc.bottom - rc.top
    usage.log.info("桌宠窗口 visible=%s rect=%s,%s %sx%s", vis, rc.left, rc.top, w, h)
    return vis and w > 40 and h > 40


def _gui_call(fn):
    """把桌宠窗体操作投递回其 WinForms UI 线程。

    这个入口也会被 HTTP 设置回调和托盘线程调用。它们都不能直接操作
    ``PetView.form``，否则 Windows 会把宿主进程标为“无响应”。
    """
    view = _state.get("pet_view")
    native = getattr(view, "form", None) if view else None
    if native is None:
        window = _state.get("window")
        native = getattr(window, "native", None) if window else None
    try:
        from System import Action
        if native is not None:
            if getattr(native, "InvokeRequired", False):
                native.BeginInvoke(Action(fn))
                return True
            # 只有已确认就在 UI 线程时才允许同步调用。
            fn()
            return True
    except Exception:
        usage.log.warning("桌宠显隐切回界面线程失败", exc_info=True)
        # native 已存在却投递失败时，绝不能退回到调用方线程直接触碰 WinForms。
        return False
    # 桌宠窗体尚未创建：设置请求已经写入 show_pet 元数据，创建时会读取它。
    return False


def _hook_show_pet():
    _gui_call(show_pet_window)


def _hook_hide_pet():
    _gui_call(hide_pet_window)


def _hook_apply_pet_settings(settings):
    def _apply():
        view = _state.get("pet_view")
        if view:
            view.apply_pet_settings(settings)
            return
        eng = ensure_engine()
        eng.set_mode(settings.get("pet_mode", eng.mode))
        eng.set_speech_level(settings.get("pet_speech", eng.speech_level))
        eng.set_custom_lines(settings.get("pet_lines", eng.custom_lines))
        eng.set_pet_pack(settings.get("pet_pack", eng.pet_pack_id))
    _gui_call(_apply)


def _hook_companion_action(action, snapshot):
    """执行伙伴页的明确指令，并复用当前桌宠引擎与渲染通道。"""
    def _apply():
        eng = ensure_engine()
        reply = str((snapshot or {}).get("reply") or "").strip()
        if action == "hello":
            eng.jump_t = 1.0
            eng.say(reply or "我在，继续加油。", stream=bool(reply))
        elif action == "walk":
            eng.set_mode("wander")
            eng.rest_until = 0
            eng.action, eng.action_t = "sway", 1.0
            eng.say(reply or "出去走走，活动一下。", stream=bool(reply))
        elif action == "celebrate":
            eng.jump_t = 1.0
            eng.action, eng.action_t = "sway", 1.0
            eng.say(reply or "完成得漂亮！", stream=bool(reply))
        elif action == "rest":
            eng.set_mode("still")
            eng.action, eng.action_t = "stretch", 1.0
            eng.say(reply or "休息一下，回来再继续。", stream=bool(reply))
        elif action == "home":
            eng.set_mode("still")
            eng.work = logical_work_area(pet_hwnd())
            eng.x, eng.y = pet_geom.default_pet_pos_from_work(eng.work, eng.win_w, eng.win_h)
            move_pet_native(eng.x, eng.y)
            eng.say(reply or "我先回到角落等你。", stream=bool(reply))
        else:
            return False
        push_pet_js_async(pose_payload(eng, {"jump": eng.jump_t, "action": eng.action or "", "say": eng.bubble_text}))
        return True
    return bool(_gui_call(_apply))


def show_pet_window():
    v = _state.get("pet_view")
    if v:
        try:
            v.show()
        except Exception:
            pass
    try:
        if usage.Handler.store:
            usage.Handler.store.set_meta("show_pet", "1")
    except Exception:
        pass


def hide_pet_window():
    v = _state.get("pet_view")
    if v:
        try:
            v.hide()
        except Exception:
            pass
    try:
        if usage.Handler.store:
            usage.Handler.store.set_meta("show_pet", "0")
    except Exception:
        pass


def restore_pet_after_dashboard():
    """面板关闭后按用户原有开关恢复桌宠，不改变持久化设置。"""
    if not pet_enabled():
        return
    view = _state.get("pet_view")
    if view:
        try:
            view.show()
        except Exception:
            pass


def _toggle_pet_from_tray():
    """托盘回调运行在 pystray 线程，只能投递桌宠显隐请求。"""
    if pet_enabled():
        _hook_hide_pet()
    else:
        _hook_show_pet()


class PetBridge:
    def open_panel(self):
        bring_to_front()

    def hide_pet(self):
        hide_pet_window()

    def show_pet(self):
        show_pet_window()

    def win_pos(self):
        eng = _state.get("engine")
        if eng:
            return [int(eng.x), int(eng.y)]
        p = _state.get("pet")
        if not p:
            return [0, 0]
        try:
            return [int(p.x), int(p.y)]
        except Exception:
            return [0, 0]

    def move_win(self, x, y):
        p = _state.get("pet")
        eng = _state.get("engine")
        if eng:
            eng.x, eng.y = float(x), float(y)
        if p:
            try:
                p.move(int(x), int(y))
            except Exception:
                pass

    def save_pos(self, x, y):
        meta_set("pet_x", int(x))
        meta_set("pet_y", int(y))

    def begin_drag(self):
        start_native_drag()

    def drag_to(self, origin_wx, origin_wy, origin_sx, origin_sy, sx, sy):
        return None

    def end_drag(self):
        _state["drag_alive"] = False
        sync_engine_from_window()
        eng = ensure_engine()
        extra = {}
        if eng.dragging:
            extra = eng.on_drag_end(bool(_state.get("drag_moved")))
        meta_set("pet_x", int(eng.x))
        meta_set("pet_y", int(eng.y))
        payload = pose_payload(eng)
        if extra.get("say"):
            payload["say"] = extra["say"]
            payload["inner"] = extra.get("inner", False)
        payload["moved"] = bool(_state.get("drag_moved"))
        return payload

    def pet_click(self):
        eng = ensure_engine()
        extra = eng.on_click()
        payload = pose_payload(eng)
        if extra.get("jump"):
            payload["jump"] = extra["jump"]
        if extra.get("say"):
            payload["say"] = extra["say"]
            payload["inner"] = extra.get("inner", False)
        return payload

    def set_mode(self, mode):
        eng = ensure_engine()
        eng.set_mode(str(mode or "wander"))
        meta_set("pet_mode", eng.mode)
        return pose_payload(eng)

    def set_size(self, label):
        eng = ensure_engine()
        if not eng.set_size(str(label or "中")):
            return pose_payload(eng)
        meta_set("pet_size", eng.size_label)
        p = _state.get("pet")
        if p:
            try:
                p.resize(int(eng.win_w), int(eng.win_h))
            except Exception:
                pass
        move_pet_native(eng.x, eng.y)
        return pose_payload(eng)

    def snap_pet(self):
        eng = ensure_engine()
        hwnd = user32.FindWindowW(None, PET_TITLE)
        eng.work = logical_work_area(hwnd)
        eng.snap()
        p = _state.get("pet")
        if p:
            try:
                p.move(int(eng.x), int(eng.y))
            except Exception:
                pass
        meta_set("pet_x", int(eng.x))
        meta_set("pet_y", int(eng.y))
        return pose_payload(eng)

    def pet_state(self):
        eng = ensure_engine()
        data = pose_payload(eng)
        if eng.bubble_text and (eng.now_ms() / 1000.0) < eng.bubble_until:
            data["say"] = eng.bubble_text
            data["inner"] = eng.bubble_inner
        return data

    def pet_step(self):
        eng = _state.get("engine")
        p = _state.get("pet")
        if not eng or not p or eng.dragging:
            return None
        hwnd = user32.FindWindowW(None, PET_TITLE)
        eng.work = logical_work_area(hwnd)
        eng.away = live_away()
        cursor = cursor_logical(hwnd) if eng.mode == "follow" else None
        events = eng.tick(cursor=cursor)
        extra = {}
        if events.get("pos"):
            try:
                p.move(int(eng.x), int(eng.y))
            except Exception:
                pass
            now = time.time()
            if now - float(_state.get("pet_save_ts") or 0) > 12:
                _state["pet_save_ts"] = now
                meta_set("pet_x", int(eng.x))
                meta_set("pet_y", int(eng.y))
        if events.get("jump"):
            extra["jump"] = events["jump"]
        if events.get("action"):
            extra["action"] = events["action"]
        if events.get("say"):
            extra["say"] = events["say"]
            extra["inner"] = events.get("inner", False)
        if events.get("pose") or extra or events.get("pos"):
            return pose_payload(eng, extra)
        return pose_payload(eng) if eng.away else None


def place_pet():
    p = _state.get("pet")
    if not p:
        return
    hwnd = user32.FindWindowW(None, PET_TITLE)
    work = logical_work_area(hwnd)
    size_label = load_pet_size()
    win_w, win_h = pet_geom.window_size(pet_geom.SIZE_H[size_label])
    eng = _state.get("engine")
    if eng:
        win_w, win_h = eng.win_w, eng.win_h
        eng.work = work
    x = y = None
    try:
        xs, ys = meta_get("pet_x", None), meta_get("pet_y", None)
        if xs not in (None, "") and ys not in (None, ""):
            x, y = int(xs), int(ys)
    except Exception:
        x = y = None
    if x is None or y is None:
        x, y = pet_geom.default_pet_pos_from_work(work, win_w, win_h)
    else:
        x, y = pet_geom.clamp_pet_pos(x, y, work, win_w, win_h)
    try:
        p.move(int(x), int(y))
        usage.log.info("桌宠逻辑坐标 %s,%s 工作区 %s", x, y, work)
    except Exception as e:
        usage.log.warning("桌宠定位失败：%s", e)
    eng = ensure_engine(x, y)
    eng.x, eng.y = float(x), float(y)
    eng.work = work


def pet_enabled():
    try:
        store = usage.Handler.store
        if store:
            return (store.get_meta("show_pet") or "1") != "0"
    except Exception:
        pass
    return True


def apply_window_icon():
    if not os.path.isfile(ICON_PATH):
        return
    hwnd = user32.FindWindowW(None, APP_TITLE)
    if not hwnd:
        return
    hicon = user32.LoadImageW(None, ICON_PATH, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
    if hicon:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)


def load_tray_image():
    from PIL import Image
    for path in (ICON_PNG, ICON_PATH):
        if os.path.isfile(path):
            return Image.open(path)
    return Image.new("RGBA", (32, 32), (62, 224, 143, 255))


def quit_app():
    _state["exiting"] = True
    _state["pet_run"] = False
    _state["drag_alive"] = False
    tray = _state.get("tray")
    if tray:
        try:
            tray.stop()
        except Exception:
            pass
    v = _state.get("pet_view")
    if v:
        try:
            v.close()
        except Exception:
            pass
    for key in ("pet", "window"):
        w = _state.get(key)
        if w:
            try:
                w.destroy()
            except Exception:
                pass


def start_tray():
    import pystray

    def on_open(icon, item):
        bring_to_front()

    def on_quit(icon, item):
        quit_app()

    def on_toggle_pet(icon, item):
        _toggle_pet_from_tray()

    def on_focus_toggle(icon, item):
        """托盘中的低打扰专注快捷操作。"""
        try:
            import pomodoro_util
            snap = pomodoro_util.snapshot()
            if snap.get("mode") in ("focus", "break", "paused"):
                pomodoro_util.toggle_pause()
            else:
                focus, brk = pomodoro_util.load_from_store(getattr(usage.Handler, "store", None))
                pomodoro_util.start(focus, brk)
        except Exception as e:
            usage.log.warning("托盘番茄钟操作失败：%s", e)

    def focus_label(item):
        try:
            import pomodoro_util
            snap = pomodoro_util.snapshot()
            mode = snap.get("mode")
            if mode == "paused":
                return "继续专注"
            if mode in ("focus", "break"):
                return "暂停专注"
        except Exception:
            pass
        return "开始专注"

    image = load_tray_image()
    menu = pystray.Menu(
        pystray.MenuItem("打开面板", on_open, default=True),
        pystray.MenuItem("本地记录中", None, enabled=False),
        pystray.MenuItem(focus_label, on_focus_toggle),
        pystray.MenuItem("显示/隐藏桌宠", on_toggle_pet),
        pystray.MenuItem("退出", on_quit),
    )
    icon = pystray.Icon("Ticko", image, APP_TITLE, menu)
    _state["tray"] = icon
    icon.run()


def main():
    set_app_id()
    _mutex, already = acquire_mutex()
    if already:
        if not bring_to_front():
            alert("软件已经在运行，请点任务栏右下角托盘图标打开。")
        return
    stop_stale()
    url = usage.start_backend(serve_in_thread=True)
    if not url:
        if not bring_to_front():
            alert("无法启动采集服务。请查看 data\\app.log")
        return
    if not wait_ready(url):
        alert("服务启动超时。请查看 data\\app.log")
        usage.shutdown_backend()
        return
    usage.register_pet_hooks(_hook_show_pet, _hook_hide_pet, _hook_apply_pet_settings, _hook_companion_action)
    try:
        import webview
    except Exception:
        alert("缺少界面组件 pywebview，无法打开窗口。")
        usage.shutdown_backend()
        return

    show_pet = pet_enabled()
    size_label = load_pet_size()
    pet_w, pet_h = pet_geom.window_size(pet_geom.SIZE_H[size_label])
    work0 = logical_work_area()
    pet_x, pet_y = pet_geom.default_pet_pos_from_work(work0, pet_w, pet_h)
    try:
        xs, ys = meta_get("pet_x", None), meta_get("pet_y", None)
        if xs not in (None, "") and ys not in (None, ""):
            pet_x, pet_y = pet_geom.clamp_pet_pos(int(xs), int(ys), work0, pet_w, pet_h)
    except Exception:
        pass
    window = webview.create_window(
        APP_TITLE,
        url,
        width=1440,
        height=900,
        min_size=(960, 640),
        text_select=True,
        hidden=True,
    )
    _state["window"] = window

    def on_closing():
        if _state["exiting"]:
            return True
        try:
            window.hide()
        except Exception:
            pass
        restore_pet_after_dashboard()
        return False

    window.events.closing += on_closing
    threading.Thread(target=start_tray, daemon=True).start()

    def _shown():
        try:
            window.events.shown.wait(15)
        except Exception:
            pass
        time.sleep(0.2)
        apply_window_icon()
        # pywebview 6.x：hidden=True 创建的窗口不会自动显示，必须显式 show。
        try:
            window.show()
            window.restore()
        except Exception as e:
            usage.log.warning("面板窗口显示失败：%s", e)
        ensure_engine(pet_x, pet_y)
        eng = _state.get("engine")
        if eng:
            eng.x, eng.y = float(pet_x), float(pet_y)
            eng.work = logical_work_area()
        view = pet_view.PetView(sys.modules[__name__])
        _state["pet_view"] = view
        try:
            view.start(window, show=show_pet)
            if show_pet:
                # PetView 会按初始设置创建窗体；这里再次显式显示，避免
                # WebView 初始化期间的焦点/可见性切换把已勾选的桌宠藏起来。
                view.show()
        except Exception as e:
            usage.log.warning("桌宠窗口创建失败：%s", e)
        if not log_pet_geom():
            usage.log.warning("桌宠窗口不可见，请检查 DPI 坐标")

    try:
        # private_mode=False + storage_path：持久化 WebView2 缓存，
        # 避免每次启动都用全新临时缓存（首屏黑屏/加载慢）。
        _cache_dir = os.path.join(
            os.environ.get("APPDATA", os.path.dirname(SCRIPT_DIR)),
            "Ticko",
            "webview_cache",
        )
        try:
            os.makedirs(_cache_dir, exist_ok=True)
        except Exception:
            pass
        webview.start(
            _shown,
            gui="edgechromium",
            icon=ICON_PATH,
            private_mode=False,
            storage_path=_cache_dir,
        )
    except TypeError:
        try:
            webview.start(_shown, gui="edgechromium")
        except Exception as e:
            alert("无法打开应用窗口：%s" % e)
    except Exception as e:
        alert("无法打开应用窗口：%s" % e)
    finally:
        _state["exiting"] = True
        _state["pet_run"] = False
        _state["drag_alive"] = False
        tray = _state.get("tray")
        if tray:
            try:
                tray.stop()
            except Exception:
                pass
        usage.shutdown_backend()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            logp = os.path.join(os.path.dirname(SCRIPT_DIR), "data", "crash.log")
            os.makedirs(os.path.dirname(logp), exist_ok=True)
            with open(logp, "a", encoding="utf-8") as f:
                import traceback
                f.write(traceback.format_exc())
        except Exception:
            pass
        try:
            alert("启动失败：%s" % e)
        except Exception:
            pass
        raise
