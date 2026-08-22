# -*- coding: utf-8 -*-
"""本地提醒音：内置几段 WAV，可上传自己的音频，不联网。"""
import math
import os
import re
import struct
import threading
import uuid
import wave

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
SOUND_DIR = os.path.join(BASE_DIR, "data", "sounds")
BUILTIN_DIR = os.path.join(SOUND_DIR, "builtin")
CUSTOM_DIR = os.path.join(SOUND_DIR, "custom")
MAX_AUDIO_BYTES = 8 * 1024 * 1024
ALLOWED_EXT = {".wav", ".mp3", ".ogg", ".m4a", ".aac"}
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
RATE = 22050

BUILTIN = (
    ("chime", "清铃"),
    ("wood", "木鱼"),
    ("ping", "双音"),
    ("urgent", "急促"),
)

_play_lock = threading.Lock()
_mci_alias = "ticko_alert"
SILENT = False


def _clamp_sample(v):
    return max(-32767, min(32767, int(v)))


def _write_wav(path, samples, rate=RATE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    packed = struct.pack("<%dh" % len(samples), *[_clamp_sample(s) for s in samples])
    with wave.open(path, "w") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(packed)


def _tone(freq, dur, vol=0.38, decay=True, rate=RATE):
    n = max(1, int(rate * dur))
    out = []
    for i in range(n):
        t = i / float(rate)
        env = min(1.0, i / 90.0)
        if decay:
            env *= math.exp(-3.2 * t / max(dur, 0.05))
        out.append(32767 * vol * env * math.sin(2 * math.pi * freq * t))
    return out


def _silence(dur, rate=RATE):
    return [0] * max(1, int(rate * dur))


def _make_chime():
    a = _tone(880, 0.55, vol=0.34)
    b = _tone(1320, 0.7, vol=0.22)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return [a[i] + b[i] for i in range(n)]


def _make_wood():
    n = int(RATE * 0.28)
    out = []
    for i in range(n):
        t = i / float(RATE)
        env = math.exp(-18 * t)
        noise = ((i * 1103515245 + 12345) & 0x7FFF) / 32768.0 - 0.5
        thud = math.sin(2 * math.pi * 180 * t)
        out.append(32767 * 0.55 * env * (0.35 * noise + 0.8 * thud))
    return out


def _make_ping():
    return _tone(523.25, 0.22, vol=0.36) + _silence(0.08) + _tone(659.25, 0.38, vol=0.36)


def _make_urgent():
    beep = _tone(980, 0.12, vol=0.4, decay=False)
    gap = _silence(0.08)
    return beep + gap + beep + gap + beep


def ensure_defaults():
    os.makedirs(BUILTIN_DIR, exist_ok=True)
    os.makedirs(CUSTOM_DIR, exist_ok=True)
    makers = {
        "chime": _make_chime,
        "wood": _make_wood,
        "ping": _make_ping,
        "urgent": _make_urgent,
    }
    for sid, _name in BUILTIN:
        path = os.path.join(BUILTIN_DIR, sid + ".wav")
        if not os.path.isfile(path) or os.path.getsize(path) < 200:
            _write_wav(path, makers[sid]())
    return True


def _store():
    try:
        import app as usage
        return usage.Handler.store
    except Exception:
        return None


def selected_id(store=None):
    store = store or _store()
    sid = "chime"
    if store:
        try:
            sid = (store.get_meta("alarm_sound_id") or "chime").strip() or "chime"
        except Exception:
            sid = "chime"
    if not resolve_path(sid):
        return "chime"
    return sid


def save_selected(store, sid):
    if not resolve_path(sid):
        sid = "chime"
    if store:
        store.set_meta("alarm_sound_id", sid)
    return sid


def resolve_path(sid):
    ensure_defaults()
    if not sid or not ID_RE.match(sid):
        return None
    for folder, ext in ((BUILTIN_DIR, ".wav"), (CUSTOM_DIR, None)):
        if ext:
            path = os.path.join(folder, sid + ext)
            if os.path.isfile(path):
                return path
            continue
        for name in os.listdir(folder) if os.path.isdir(folder) else []:
            stem, found_ext = os.path.splitext(name)
            if stem == sid and found_ext.lower() in ALLOWED_EXT:
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    return path
    return None


def list_sounds(store=None):
    ensure_defaults()
    current = selected_id(store)
    items = []
    for sid, name in BUILTIN:
        items.append({
            "id": sid,
            "name": name,
            "builtin": True,
            "selected": sid == current,
        })
    if os.path.isdir(CUSTOM_DIR):
        for name in sorted(os.listdir(CUSTOM_DIR)):
            stem, ext = os.path.splitext(name)
            if ext.lower() not in ALLOWED_EXT or not ID_RE.match(stem):
                continue
            items.append({
                "id": stem,
                "name": stem,
                "builtin": False,
                "selected": stem == current,
            })
    return {"items": items, "selected": current}


def save_upload(filename, payload):
    ensure_defaults()
    if not payload or len(payload) > MAX_AUDIO_BYTES:
        return None, "文件太大或为空（最大 8MB）"
    orig = os.path.basename(filename or "alert.wav")
    ext = os.path.splitext(orig)[1].lower()
    if ext not in ALLOWED_EXT:
        return None, "仅支持 wav / mp3 / ogg / m4a"
    sid = "u" + uuid.uuid4().hex[:12]
    path = os.path.join(CUSTOM_DIR, sid + ext)
    with open(path, "wb") as fh:
        fh.write(payload)
    return sid, None


def delete_custom(sid, store=None):
    if not sid or sid in {x[0] for x in BUILTIN}:
        return False
    path = resolve_path(sid)
    if not path or BUILTIN_DIR in os.path.abspath(path):
        return False
    try:
        os.remove(path)
    except Exception:
        return False
    store = store or _store()
    if store and selected_id(store) == sid:
        save_selected(store, "chime")
    return True


def _mci(cmd):
    import ctypes
    buf = ctypes.create_unicode_buffer(256)
    winmm = ctypes.WinDLL("winmm")
    winmm.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    winmm.mciSendStringW.restype = ctypes.c_uint
    return winmm.mciSendStringW(cmd, buf, 255, None)


def _play_path(path):
    if not path or not os.path.isfile(path):
        return False
    ext = os.path.splitext(path)[1].lower()
    with _play_lock:
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        try:
            _mci("stop " + _mci_alias)
            _mci("close " + _mci_alias)
        except Exception:
            pass
        if ext == ".wav":
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return True
            except Exception:
                pass
        quoted = path.replace("/", "\\")
        err = _mci('open "%s" type mpegvideo alias %s' % (quoted, _mci_alias))
        if err:
            err = _mci('open "%s" alias %s' % (quoted, _mci_alias))
        if err:
            return False
        _mci("play %s from 0" % _mci_alias)
        return True


def play_id(sid=None, store=None):
    if SILENT:
        return True
    ensure_defaults()
    path = resolve_path(sid or selected_id(store))
    if not path:
        path = resolve_path("chime")
    return _play_path(path)


def play_alert(store=None):
    return play_id(selected_id(store), store)


def play_alert_async(store=None):
    threading.Thread(target=play_alert, args=(store,), daemon=True).start()
