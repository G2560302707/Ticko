# -*- coding: utf-8 -*-
"""Ticko 本地语音：短语音转写与 Windows 本地朗读。"""

import asyncio
import audioop
import ctypes
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
import wave
import queue
import winsound


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(SCRIPT_DIR, "models", "vosk-model-small-cn-0.22")
PIPER_DIR = os.path.join(SCRIPT_DIR, "models", "piper")
PIPER_MODEL = os.path.join(PIPER_DIR, "zh_CN-huayan-medium.onnx")
MAX_AUDIO_BYTES = 5 * 1024 * 1024
MAX_SECONDS = 22
_model = None
_model_lock = threading.Lock()
_listen_lock = threading.Lock()
_listen_state = {"state": "idle", "text": "", "error": ""}
_listen_cancel = threading.Event()
_listen_generation = 0
_speech_lock = threading.Lock()
_speech_jobs = 0
_piper_voice = None
_piper_lock = threading.Lock()

# 在线音色作为主声音；网络不可用时自动回退 Ticko 内置离线声音。
VOICE_PRESETS = {
    "cute": {"label": "软萌小艺", "voice": "zh-CN-XiaoyiNeural", "rate": "+6%"},
    "sweet": {"label": "甜美晓晓", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+3%"},
    "lively": {"label": "元气云希", "voice": "zh-CN-YunxiNeural", "rate": "+10%"},
    "calm": {"label": "沉稳云健", "voice": "zh-CN-YunjianNeural", "rate": "-5%"},
}


def available():
    try:
        import vosk  # noqa: F401
        return os.path.isdir(MODEL_DIR)
    except Exception:
        return False


def status():
    return {
        "available": available(),
        "mode": "本地识别" if available() else "语音模型未就绪",
        "voices": [{"id": key, "label": item["label"]} for key, item in VOICE_PRESETS.items()],
        "offline_voice": os.path.isfile(PIPER_MODEL),
    }


def is_speaking():
    with _speech_lock:
        return _speech_jobs > 0


def warmup_offline_voice():
    """后台预热离线模型，避免第一次开口才产生加载延迟。"""
    if not os.path.isfile(PIPER_MODEL):
        return False
    def work():
        try:
            _load_piper_voice()
        except Exception:
            pass
    threading.Thread(target=work, name="TickoVoiceWarmup", daemon=True).start()
    return True


def _set_speaking(change):
    global _speech_jobs
    with _speech_lock:
        _speech_jobs = max(0, _speech_jobs + change)


def _load_piper_voice():
    """加载一次本地中文语音；通过 ASCII 目录兼容 Windows ONNX 运行库。"""
    global _piper_voice
    if not os.path.isfile(PIPER_MODEL):
        return None
    with _piper_lock:
        if _piper_voice is None:
            from piper import PiperVoice
            model_path = PIPER_MODEL
            drive = os.path.splitdrive(model_path)[0] or "C:"
            if any(ord(char) > 127 for char in model_path):
                alias = drive + os.sep + "TickoTtsModel"
                if not os.path.exists(alias):
                    subprocess.run(["cmd.exe", "/c", "mklink", "/J", alias, os.path.dirname(model_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                candidate = os.path.join(alias, os.path.basename(model_path))
                if os.path.isfile(candidate):
                    model_path = candidate
            # Piper 的语音数据随包安装；ONNX/phonemizer 在 Windows 下需要 ASCII 路径。
            package_data = os.path.join(os.path.dirname(__import__("piper").__file__), "espeak-ng-data")
            espeak_alias = drive + os.sep + "TickoEspeakData"
            if not os.path.exists(espeak_alias):
                subprocess.run(["cmd.exe", "/c", "mklink", "/J", espeak_alias, package_data], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _piper_voice = PiperVoice.load(model_path, espeak_data_dir=espeak_alias if os.path.isdir(espeak_alias) else package_data)
    return _piper_voice


def _speak_piper(text, rate=0):
    """离线合成并播放一小段语句，文件在播放后立即删除。"""
    voice = _load_piper_voice()
    if voice is None:
        raise RuntimeError("offline voice unavailable")
    temp_path = ""
    try:
        handle = tempfile.NamedTemporaryFile(prefix="ticko_local_voice_", suffix=".wav", delete=False)
        temp_path = handle.name
        from piper.config import SynthesisConfig
        # 语速仍沿用 Ticko 的 -4 ~ +4 设置，完全在本地推理时生效。
        length_scale = max(0.82, min(1.18, 1.0 - (float(rate) * 0.045)))
        with wave.open(handle, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file, syn_config=SynthesisConfig(length_scale=length_scale))
        winsound.PlaySound(temp_path, winsound.SND_FILENAME)
        return True
    finally:
        if temp_path:
            for _ in range(3):
                try:
                    os.remove(temp_path)
                    break
                except OSError:
                    time.sleep(0.12)


def _load_model():
    global _model
    if not available():
        return None
    with _model_lock:
        if _model is None:
            import vosk
            vosk.SetLogLevel(-1)
            model_path = MODEL_DIR
            # Vosk 的 Windows 原生库不能稳定处理非 ASCII 目录。没有 8.3 短路径时，
            # 在同一磁盘根目录建立只指向应用内模型的 ASCII 连接，不复制模型文件。
            if any(ord(char) > 127 for char in model_path):
                drive = os.path.splitdrive(model_path)[0] or "C:"
                alias = drive + os.sep + "TickoVoiceModel"
                if not os.path.exists(alias):
                    subprocess.run(["cmd.exe", "/c", "mklink", "/J", alias, model_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if os.path.isdir(alias) and os.path.samefile(alias, model_path):
                    model_path = alias
            _model = vosk.Model(model_path)
    return _model


def transcribe_wav(payload):
    """转写浏览器生成的单声道 WAV；音频只存在于本次请求内存中。"""
    if not payload or len(payload) > MAX_AUDIO_BYTES:
        return "", "录音过长，请在 22 秒内说完。"
    model = _load_model()
    if model is None:
        return "", "本地语音识别尚未就绪。"
    try:
        with wave.open(io.BytesIO(payload), "rb") as source:
            channels, width, rate, frames = source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getnframes()
            if width not in (1, 2, 3, 4) or rate < 8000 or rate > 96000 or channels not in (1, 2):
                return "", "录音格式不受支持。"
            if frames / float(rate) > MAX_SECONDS:
                return "", "录音过长，请在 22 秒内说完。"
            raw = source.readframes(frames)
        if channels == 2:
            raw = audioop.tomono(raw, width, 0.5, 0.5)
        if width != 2:
            raw = audioop.lin2lin(raw, width, 2)
        if rate != 16000:
            raw, _ = audioop.ratecv(raw, 2, 1, rate, 16000, None)
        import vosk
        recognizer = vosk.KaldiRecognizer(model, 16000)
        recognizer.AcceptWaveform(raw)
        result = json.loads(recognizer.FinalResult() or "{}")
        text = " ".join(str(result.get("text") or "").split()).strip()
        return text, "" if text else "没有听清，请再说一次。"
    except (wave.Error, EOFError):
        return "", "录音文件无效。"
    except Exception:
        return "", "语音识别暂时不可用。"


def listen_status():
    """返回 Windows 原生麦克风录音的一次性状态，不保留音频数据。"""
    with _listen_lock:
        return dict(_listen_state)


def listen_once_async():
    """从系统默认麦克风监听一小段话，自动在停顿后结束。"""
    global _listen_generation
    with _listen_lock:
        if _listen_state["state"] in ("starting", "listening"):
            return False
        _listen_generation += 1
        generation = _listen_generation
        _listen_state.update({"state": "starting", "text": "", "error": ""})
    _listen_cancel.clear()

    def set_state(**values):
        with _listen_lock:
            if generation == _listen_generation:
                _listen_state.update(values)

    def worker():
        stream = None
        try:
            model = _load_model()
            if model is None:
                set_state(state="error", error="本地语音识别尚未就绪。")
                return
            import sounddevice as sd
            import vosk

            packets = queue.Queue()
            failure = []

            def capture(indata, frames, clock, status):
                if status:
                    failure.append(str(status))
                packets.put(bytes(indata))

            recognizer = vosk.KaldiRecognizer(model, 16000)
            set_state(state="listening", text="", error="")
            heard = False
            last_voice = time.monotonic()
            started = last_voice
            with sd.RawInputStream(samplerate=16000, blocksize=1600, channels=1, dtype="int16", callback=capture):
                while time.monotonic() - started < 11:
                    if _listen_cancel.is_set():
                        set_state(state="idle", text="", error="")
                        return
                    try:
                        data = packets.get(timeout=0.35)
                    except queue.Empty:
                        if heard and time.monotonic() - last_voice > 0.68:
                            break
                        continue
                    if audioop.rms(data, 2) > 150:
                        heard = True
                        last_voice = time.monotonic()
                    recognizer.AcceptWaveform(data)
                    if heard and time.monotonic() - last_voice > 0.68:
                        break
            if failure:
                raise RuntimeError(failure[-1])
            if not heard:
                set_state(state="error", error="没有收到麦克风声音，请检查系统麦克风权限。")
                return
            result = json.loads(recognizer.FinalResult() or "{}")
            text = " ".join(str(result.get("text") or "").split()).strip()
            if text:
                set_state(state="ready", text=text, error="")
            else:
                set_state(state="error", error="没有听清，请靠近麦克风再说一次。")
        except Exception as exc:
            set_state(state="error", error="无法使用系统麦克风：%s" % str(exc)[:110])

    threading.Thread(target=worker, name="TickoMic", daemon=True).start()
    return True


def stop_listening():
    """立即释放系统麦克风；由对话窗口的结束操作调用。"""
    global _listen_generation
    _listen_cancel.set()
    with _listen_lock:
        _listen_generation += 1
        _listen_state.update({"state": "idle", "text": "", "error": ""})


def speak_stream_async(text, enabled=False, rate=0, preset="cute"):
    """按自然短段连续朗读，避免在线音色在每个句号处重复建连。"""
    text = " ".join(str(text or "").split())[:280]
    if not enabled or not text:
        return False
    import re
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?；;])", text) if part.strip()]
    # 在线 TTS 若每句话单独请求，会在句号处留下明显的网络空档。
    # 将邻近短句合成一段（约 60 字）能保留标点停顿，同时让朗读连贯自然。
    pieces, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > 64:
            pieces.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        pieces.append(current)
    if not pieces:
        return False
    try:
        rate = max(-4, min(4, int(rate)))
        preset = preset if preset in VOICE_PRESETS else "cute"
        def work():
            stop_listening()
            _set_speaking(1)
            try:
                for piece in pieces:
                    try:
                        _speak_online(piece, preset)
                    except Exception:
                        try:
                            _speak_piper(piece, rate)
                        except Exception:
                            try:
                                _speak_local(piece, rate)
                            except Exception:
                                pass
            finally:
                _set_speaking(-1)
        threading.Thread(target=work, name="TickoSpeechStream", daemon=True).start()
        return True
    except Exception:
        return False


def _speak_local(text, rate):
    """使用 Windows SAPI 朗读；由后台线程调用。"""
    env = os.environ.copy()
    env["TICKO_SPEECH_TEXT"] = text
    env["TICKO_SPEECH_RATE"] = str(rate)
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$voice=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "try{$voice.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female)}catch{}; "
        "$voice.Volume=100; "
        "$voice.Rate=[int]$env:TICKO_SPEECH_RATE; "
        "$voice.Speak($env:TICKO_SPEECH_TEXT)"
    )
    subprocess.run(
        ["powershell.exe", "-STA", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=True,
    )


def _play_mp3(path):
    """通过 Windows MCI 直接输出 MP3 到默认音频设备。"""
    winmm = ctypes.WinDLL("winmm")
    send = winmm.mciSendStringW
    send.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    send.restype = ctypes.c_uint
    alias = "ticko_voice_" + uuid.uuid4().hex[:10]
    safe_path = os.path.abspath(path).replace('"', "")
    def call(command):
        result = send(command, None, 0, None)
        if result:
            raise RuntimeError("MCI audio error %s" % result)
    try:
        call('open "%s" type mpegvideo alias %s' % (safe_path, alias))
        call("play %s wait" % alias)
    finally:
        send("close %s" % alias, None, 0, None)


def _speak_online(text, preset):
    """生成临时 MP3 并播放，播放完成后立即删除，不留语音缓存。"""
    import edge_tts

    voice = VOICE_PRESETS[preset]
    temp_path = ""
    try:
        handle = tempfile.NamedTemporaryFile(prefix="ticko_voice_", suffix=".mp3", delete=False)
        temp_path = handle.name
        handle.close()
        async def render():
            audio = edge_tts.Communicate(text, voice=voice["voice"], rate=voice["rate"])
            await audio.save(temp_path)
        asyncio.run(render())
        _play_mp3(temp_path)
        return True
    finally:
        if temp_path:
            for _ in range(3):
                try:
                    os.remove(temp_path)
                    break
                except OSError:
                    time.sleep(0.12)


def speak_async(text, enabled=False, rate=0, preset="cute"):
    """异步朗读：优先在线高质量声音，失败后回退内置离线声音。"""
    text = " ".join(str(text or "").split())[:280]
    if not enabled or not text:
        return False
    try:
        rate = max(-4, min(4, int(rate)))
        preset = preset if preset in VOICE_PRESETS else "cute"
        def work():
            stop_listening()
            _set_speaking(1)
            try:
                _speak_online(text, preset)
            except Exception:
                try:
                    _speak_piper(text, rate)
                except Exception:
                    try:
                        _speak_local(text, rate)
                    except Exception:
                        pass
            finally:
                _set_speaking(-1)
        threading.Thread(target=work, name="TickoSpeech", daemon=True).start()
        return True
    except Exception:
        return False
