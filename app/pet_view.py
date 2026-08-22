# -*- coding: utf-8 -*-
"""按像素透明的桌宠窗口（UpdateLayeredWindow），没有白底方框。"""
import ctypes
import math
import os
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

import pet_engine
import pet_geom

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPRITE_DIR = os.path.join(SCRIPT_DIR, "pet", "sprites")
TICK = pet_engine.TICK
CLEAR = (0, 0, 0, 0)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
ULW_ALPHA = 2
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
BI_RGB = 0
DIB_RGB_COLORS = 0
LONG_PTR = ctypes.c_ssize_t


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.c_void_p,
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def _log(msg, *args):
    try:
        import app as usage
        usage.log.info(msg, *args)
    except Exception:
        pass


def _sprite_path(kind, height):
    return os.path.join(SPRITE_DIR, "%s_%s.png" % (kind, int(height)))


def _fit_sprite(image, height):
    image = image.convert("RGBA")
    target_h = max(24, int(height))
    scale = target_h / float(max(1, image.height))
    target_w = max(8, int(round(image.width * scale)))
    max_w = max(24, int(round(target_h * 1.1)))
    if target_w > max_w:
        target_h = max(24, int(round(target_h * max_w / float(target_w))))
        target_w = max_w
    if image.size != (target_w, target_h):
        image = image.resize((target_w, target_h), Image.LANCZOS)
    return image


def load_sprites(height, sprite_dir=None):
    out = {}
    custom = bool(sprite_dir and os.path.isdir(sprite_dir))
    for kind in ("front", "side", "back"):
        if custom:
            path = os.path.join(sprite_dir, kind + ".png")
            if not os.path.isfile(path):
                path = os.path.join(sprite_dir, "front.png")
        else:
            path = _sprite_path(kind, height)
            if not os.path.isfile(path):
                path = os.path.join(SPRITE_DIR, kind + ".png")
        try:
            out[kind] = _fit_sprite(Image.open(path), height)
        except Exception:
            fallback = _sprite_path(kind, height)
            if not os.path.isfile(fallback):
                fallback = os.path.join(SPRITE_DIR, kind + ".png")
            out[kind] = _fit_sprite(Image.open(fallback), height)
    return out


def _font(size):
    for name in ("msyh.ttc", "msyh.ttf", "simhei.ttf", "segoeui.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def compose_frame(eng, sprites):
    w, h = int(eng.win_w), int(eng.win_h)
    canvas = Image.new("RGBA", (w, h), CLEAR)
    kind = pet_engine.sprite_name(eng.dir)
    spr = sprites.get(kind) or sprites["front"]
    spr = spr.copy()
    if eng.dir in ("left", "right") and eng.facing < 0:
        spr = ImageOps.mirror(spr)
    if eng.away:
        spr = ImageEnhance.Brightness(spr).enhance(0.72)
        spr = ImageEnhance.Color(spr).enhance(0.85)
    now = eng.t * TICK / 1000.0
    walking = eng.target is not None and not eng.dragging and not eng.away
    if walking:
        sway = math.sin(now * 9.0) * 3.5
        bob = -abs(math.sin(now * 4.5)) * 7.0
    else:
        sway = math.sin(now * 2.5) * 1.5
        bob = 6.0 if eng.away else 0.0
    breath = 1.0 + 0.02 * math.sin(now * 2.5)
    jump = 0.0
    if eng.jump_t > 0:
        jump = -abs(math.sin(eng.jump_t * math.pi)) * 14.0 * eng.jump_t
    rot = sway
    sx = sy = 1.0
    if eng.action == "sway":
        rot += math.sin(eng.action_t * math.pi * 2) * 10.0 * eng.action_t
    elif eng.action == "stretch":
        sy += 0.06 * math.sin(eng.action_t * math.pi)
        sx -= 0.03 * math.sin(eng.action_t * math.pi)
    if eng.away:
        rot -= 8.0
    nw = max(8, int(spr.width * breath * sx))
    nh = max(8, int(spr.height * breath * sy))
    spr = spr.resize((nw, nh), Image.LANCZOS)
    if abs(rot) > 0.4:
        spr = spr.rotate(rot, resample=Image.BICUBIC, expand=True, fillcolor=CLEAR)
    px = (w - spr.width) // 2
    py = h - spr.height - 2 + int(jump + bob)
    canvas.paste(spr, (px, py), spr)
    overlay = getattr(eng, "status_overlay", "") or ""
    speaking = bool(eng.bubble_text) and (eng.now_ms() / 1000.0) < eng.bubble_until
    next_y = 4
    if overlay:
        next_y = _draw_timer_chip(canvas, overlay, eng.sprite_h)
    if speaking:
        _draw_bubble(canvas, eng.bubble_text, eng.bubble_inner, eng.sprite_h, top=next_y)
    return canvas


def _text_wh(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return max(8, 8 * len(text)), 14


def _wrap_text(draw, text, font, max_w):
    lines = []
    cur = ""
    for ch in str(text):
        trial = cur + ch
        tw = _text_wh(draw, trial, font)[0]
        if cur and tw > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_timer_chip(canvas, text, sprite_h):
    metrics = pet_geom.bubble_metrics(sprite_h)
    draw = ImageDraw.Draw(canvas)
    font = _font(max(12, metrics["font"] - 1))
    tw, th = _text_wh(draw, text, font)
    pad_x, pad_y = max(9, metrics["pad_x"] - 3), max(4, metrics["pad_y"] - 3)
    dot = max(5, th // 3)
    gap = 6
    bw = tw + pad_x * 2 + dot + gap
    bh = max(th + pad_y * 2, dot + pad_y * 2)
    x = max(4, (canvas.width - bw) // 2)
    y = 6
    bg = (25, 34, 57, 204)
    shadow = (11, 16, 31, 64)
    fg = (139, 239, 190, 255)
    accent = (83, 220, 165, 255)
    if str(text).startswith("休息"):
        fg, accent = (164, 205, 255, 255), (99, 164, 255, 255)
    elif str(text).startswith("暂停"):
        fg, accent = (255, 215, 141, 255), (246, 185, 81, 255)
    radius = max(11, bh // 2)
    try:
        draw.rounded_rectangle((x, y + 2, x + bw, y + bh + 2), radius=radius, fill=shadow)
        draw.rounded_rectangle((x, y, x + bw, y + bh), radius=radius, fill=bg)
    except Exception:
        draw.rectangle((x, y, x + bw, y + bh), fill=bg)
    try:
        draw.rounded_rectangle((x, y, x + bw, y + bh), radius=radius, outline=(180, 205, 255, 52))
    except Exception:
        pass
    cy = y + bh // 2
    try:
        draw.ellipse((x + pad_x, cy - dot // 2, x + pad_x + dot, cy - dot // 2 + dot), fill=accent)
    except Exception:
        pass
    draw.text((x + pad_x + dot + gap, y + pad_y - 1), text, font=font, fill=fg)
    return y + bh + 6


def _draw_bubble(canvas, text, inner, sprite_h, top=4):
    metrics = pet_geom.bubble_metrics(sprite_h)
    draw = ImageDraw.Draw(canvas)
    font = _font(metrics["font"])
    max_text_w = min(metrics["max_text_w"], max(40, canvas.width - metrics["pad_x"] * 2 - 8))
    lines = _wrap_text(draw, text, font, max_text_w)
    widths = [_text_wh(draw, line, font)[0] for line in lines]
    tw = max(widths) if widths else 8
    line_h = metrics["line_h"]
    pad_x, pad_y, tail = metrics["pad_x"], metrics["pad_y"], metrics["tail"]
    bw = tw + pad_x * 2
    bh = len(lines) * line_h + pad_y * 2
    x = max(4, (canvas.width - bw) // 2)
    y = max(4, int(top))
    bg = (232, 232, 238, 235) if inner else (255, 255, 255, 235)
    fg = (125, 125, 138, 255) if inner else (60, 60, 80, 255)
    radius = max(8, metrics["font"] // 2)
    try:
        draw.rounded_rectangle((x, y, x + bw, y + bh), radius=radius, fill=bg)
    except Exception:
        draw.rectangle((x, y, x + bw, y + bh), fill=bg)
    cx = canvas.width // 2
    draw.polygon(
        [(cx, y + bh + tail), (cx - tail, y + bh), (cx + tail, y + bh)],
        fill=bg,
    )
    for i, line in enumerate(lines):
        lw = widths[i]
        tx = x + (bw - lw) // 2
        ty = y + pad_y + i * line_h - 1
        draw.text((tx, ty), line, font=font, fill=fg)


def enable_layered(hwnd):
    """Must toggle WS_EX_LAYERED off/on so UpdateLayeredWindow can run after WinForms LWA."""
    if not hwnd:
        return
    style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0)
    style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)


def _premul_bgra(im):
    im = im.convert("RGBA")
    try:
        return im.convert("RGBa").tobytes("raw", "BGRa")
    except Exception:
        raw = bytearray(im.tobytes("raw", "BGRA"))
        for i in range(0, len(raw), 4):
            a = raw[i + 3]
            if a == 255:
                continue
            if a == 0:
                raw[i] = raw[i + 1] = raw[i + 2] = 0
            else:
                raw[i] = raw[i] * a // 255
                raw[i + 1] = raw[i + 1] * a // 255
                raw[i + 2] = raw[i + 2] * a // 255
        return bytes(raw)


def blit_layered(hwnd, im, retry=True):
    if not hwnd:
        return False
    im = im.convert("RGBA")
    w, h = im.size
    raw = _premul_bgra(im)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateDIBSection(
        hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
    )
    if not hbmp or not bits:
        err = ctypes.get_last_error()
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        if hdc_screen:
            user32.ReleaseDC(None, hdc_screen)
        _log("桌宠 CreateDIBSection 失败 err=%s", err)
        return False
    ctypes.memmove(bits, raw, len(raw))
    old = gdi32.SelectObject(hdc_mem, hbmp)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    size = SIZE(w, h)
    src = POINT(0, 0)
    ok = user32.UpdateLayeredWindow(
        hwnd,
        hdc_screen,
        None,
        ctypes.byref(size),
        hdc_mem,
        ctypes.byref(src),
        0,
        ctypes.byref(blend),
        ULW_ALPHA,
    )
    err = 0 if ok else ctypes.get_last_error()
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    if ok:
        return True
    if retry:
        enable_layered(hwnd)
        return blit_layered(hwnd, im, retry=False)
    _log("桌宠 UpdateLayeredWindow 失败 err=%s hwnd=%s %sx%s", err, hwnd, w, h)
    return False


def _menu_color(r, g, b):
    from System.Drawing import Color
    return Color.FromArgb(255, int(r), int(g), int(b))


def _style_pet_menu(menu):
    """右键菜单配色贴近立绘：裙身蓝底、围裙白字、头发蓝高亮。"""
    from System.Drawing import Font
    from System.Windows.Forms import ProfessionalColorTable, ToolStripProfessionalRenderer, ToolStripRenderMode

    bg = _menu_color(40, 48, 100)
    fg = _menu_color(245, 248, 255)
    hi = _menu_color(88, 112, 176)
    hi2 = _menu_color(72, 92, 160)
    line = _menu_color(92, 108, 168)
    edge = _menu_color(148, 176, 220)

    class PetMenuTable(ProfessionalColorTable):
        def __init__(self):
            ProfessionalColorTable.__init__(self)
            try:
                self.UseSystemColors = False
            except Exception:
                pass

        def get_ToolStripDropDownBackground(self):
            return bg

        def get_ImageMarginGradientBegin(self):
            return bg

        def get_ImageMarginGradientMiddle(self):
            return bg

        def get_ImageMarginGradientEnd(self):
            return bg

        def get_MenuBorder(self):
            return edge

        def get_MenuItemBorder(self):
            return edge

        def get_MenuItemSelected(self):
            return hi

        def get_MenuItemSelectedGradientBegin(self):
            return hi

        def get_MenuItemSelectedGradientEnd(self):
            return hi2

        def get_MenuItemPressedGradientBegin(self):
            return hi2

        def get_MenuItemPressedGradientEnd(self):
            return hi

        def get_SeparatorDark(self):
            return line

        def get_SeparatorLight(self):
            return bg

    menu.ShowImageMargin = False
    menu.BackColor = bg
    menu.ForeColor = fg
    try:
        menu.Font = Font("Microsoft YaHei UI", 10)
    except Exception:
        pass
    try:
        menu.Renderer = ToolStripProfessionalRenderer(PetMenuTable())
        menu.RenderMode = ToolStripRenderMode.Professional
    except Exception:
        pass
    return fg, bg


def _add_menu_item(items, text, handler, fg, bg):
    from System.Windows.Forms import ToolStripMenuItem
    item = ToolStripMenuItem(text)
    item.ForeColor = fg
    item.BackColor = bg
    if handler is not None:
        item.Click += handler
    items.Add(item)
    return item


class PetView:
    def __init__(self, host):
        self.m = host
        self.form = None
        self.timer = None
        self.sprites = {}
        self._press = None
        self._offset = None
        self._moved = False
        self._last_save = 0
        self._work_ts = 0
        self._pomo_pause = None

    def start(self, host_window, show=True):
        self._want_show = show
        native = getattr(host_window, "native", None)
        from System import Action

        if native is None:
            self._create()
            return
        if native.InvokeRequired:
            native.Invoke(Action(self._create))
        else:
            self._create()

    def _hwnd(self):
        if not self.form:
            return 0
        h = self.form.Handle
        try:
            return int(h.ToInt64())
        except Exception:
            return int(h)

    def _create(self):
        from System.Drawing import Point, Size
        from System.Windows.Forms import (
            AutoScaleMode,
            ContextMenuStrip,
            Form,
            FormBorderStyle,
            FormStartPosition,
            MouseButtons,
            Timer,
            ToolStripSeparator,
        )

        m = self.m
        eng = m.ensure_engine()
        self.sprites = self._load_sprites(eng)
        class PetForm(Form):
            def OnPaintBackground(self, e):
                return

            def OnPaint(self, e):
                return

        form = PetForm()
        form.Text = m.PET_TITLE
        form.FormBorderStyle = getattr(FormBorderStyle, "None")
        form.ShowInTaskbar = False
        form.TopMost = True
        form.StartPosition = FormStartPosition.Manual
        try:
            form.AutoScaleMode = getattr(AutoScaleMode, "None")
        except Exception:
            pass
        try:
            form.AllowTransparency = False
        except Exception:
            pass
        form.Width = eng.win_w
        form.Height = eng.win_h
        px, py = m.logical_to_physical(eng.x, eng.y)
        form.Location = Point(int(px), int(py))
        self.form = form
        hwnd = self._hwnd()
        m._state["pet_hwnd"] = hwnd
        enable_layered(hwnd)
        self._paint(eng)

        menu = ContextMenuStrip()
        fg, bg = _style_pet_menu(menu)
        for label, mode in (("自由散步", "wander"), ("跟随鼠标", "follow"), ("原地待着", "still")):
            _add_menu_item(menu.Items, label, self._make_mode_handler(mode), fg, bg)
        menu.Items.Add(ToolStripSeparator())
        for label in ("小", "中", "大"):
            _add_menu_item(menu.Items, label, self._make_size_handler(label), fg, bg)
        menu.Items.Add(ToolStripSeparator())
        _add_menu_item(menu.Items, "今日目标…", self._on_goals, fg, bg)
        pomo = _add_menu_item(menu.Items, "番茄钟", None, fg, bg)
        try:
            _style_pet_menu(pomo.DropDown)
        except Exception:
            pomo.DropDown.BackColor = bg
            pomo.DropDown.ForeColor = fg
        _add_menu_item(pomo.DropDownItems, "开始（当前设置）", self._on_pomo_start_saved, fg, bg)
        _add_menu_item(pomo.DropDownItems, "开始 25 / 5", self._make_pomo_start(25, 5), fg, bg)
        _add_menu_item(pomo.DropDownItems, "开始 50 / 10", self._make_pomo_start(50, 10), fg, bg)
        self._pomo_pause = _add_menu_item(pomo.DropDownItems, "暂停 / 继续", self._on_pomo_pause, fg, bg)
        _add_menu_item(pomo.DropDownItems, "结束", self._on_pomo_stop, fg, bg)
        _add_menu_item(pomo.DropDownItems, "设置时间…", self._on_pomo_settings, fg, bg)
        menu.Items.Add(ToolStripSeparator())
        _add_menu_item(menu.Items, "打开对话", self._on_companion_chat, fg, bg)
        _add_menu_item(menu.Items, "结束对话并隐藏窗口", self._on_close_companion_chat, fg, bg)
        _add_menu_item(menu.Items, "打开面板", lambda s, e: m.bring_to_front(), fg, bg)
        _add_menu_item(menu.Items, "回到屏幕内", lambda s, e: self._snap(), fg, bg)
        _add_menu_item(menu.Items, "隐藏桌宠", lambda s, e: m.hide_pet_window(), fg, bg)
        try:
            menu.Opening += self._on_menu_opening
        except Exception:
            pass
        form.ContextMenuStrip = menu

        form.MouseDown += self._on_down
        form.MouseMove += self._on_move
        form.MouseUp += self._on_up
        form.FormClosing += self._on_closing

        timer = Timer()
        timer.Interval = TICK
        timer.Tick += self._on_tick
        timer.Start()
        self.timer = timer

        if self._want_show and m.pet_enabled():
            form.Show()
            enable_layered(self._hwnd())
            m.apply_pet_tool_style()
            enable_layered(self._hwnd())
            self._paint(eng)
        m._state["pet_hwnd"] = self._hwnd()
        _log("桌宠分层窗口 hwnd=%s visible=%s", self._hwnd(), bool(form.Visible))

    def _make_mode_handler(self, mode):
        def _h(sender, args):
            eng = self.m.ensure_engine()
            eng.set_mode(mode)
            self.m.meta_set("pet_mode", eng.mode)
        return _h

    def _make_size_handler(self, label):
        def _h(sender, args):
            self._apply_size(label)
        return _h

    def _load_sprites(self, eng):
        resolver = getattr(self.m, "pet_sprite_dir", None)
        folder = resolver(eng.pet_pack_id) if resolver else None
        return load_sprites(eng.sprite_h, folder)

    def _on_menu_opening(self, sender, args):
        import pomodoro_util
        snap = pomodoro_util.snapshot()
        if not self._pomo_pause:
            return
        mode = snap.get("mode")
        if mode == "paused":
            self._pomo_pause.Text = "继续"
        elif mode in ("focus", "break"):
            self._pomo_pause.Text = "暂停"
        else:
            self._pomo_pause.Text = "暂停 / 继续"

    def _on_goals(self, sender, args):
        self.m.open_dashboard_page("#settings")
        self.m.ensure_engine().say("去面板改今日目标")

    def _on_companion_chat(self, sender, args):
        self.m.open_companion_chat_window()
        self.m.ensure_engine().say("对话已打开，请对我说话。")

    def _on_close_companion_chat(self, sender, args):
        self.m.close_companion_chat_window()
        self.m.ensure_engine().say("对话已结束。")

    def _on_pomo_settings(self, sender, args):
        self.m.open_dashboard_page("#timer")
        self.m.ensure_engine().say("去面板看番茄钟")

    def _tick_pomodoro(self, eng):
        import pomodoro_util
        pomodoro_util.tick()
        evt = pomodoro_util.take_speech_event()
        if evt == "focus_done":
            eng.quiet = False
            eng.say("休息一下吧")
        elif evt == "break_done":
            eng.quiet = False
            eng.say("本轮番茄完成")
        snap = pomodoro_util.snapshot()
        running = snap.get("mode") in ("focus", "break", "paused")
        eng.quiet = running
        eng.status_overlay = pomodoro_util.format_overlay(snap) if running else ""

    def _make_pomo_start(self, focus, brk):
        def _h(sender, args):
            import pomodoro_util
            pomodoro_util.start(focus, brk)
            self.m.ensure_engine().say("开始专注 %d 分钟" % int(focus))
        return _h

    def _on_pomo_start_saved(self, sender, args):
        import pomodoro_util
        try:
            import app as usage
            store = usage.Handler.store
        except Exception:
            store = None
        focus, brk = pomodoro_util.load_from_store(store)
        pomodoro_util.start(focus, brk)
        self.m.ensure_engine().say("开始专注 %d 分钟" % int(focus))

    def _on_pomo_pause(self, sender, args):
        import pomodoro_util
        snap = pomodoro_util.snapshot()
        if snap.get("mode") == "idle":
            self.m.ensure_engine().say("还没开始番茄钟")
            return
        pomodoro_util.toggle_pause()
        after = pomodoro_util.snapshot()
        if after.get("mode") == "paused":
            self.m.ensure_engine().say("番茄钟已暂停")
        else:
            self.m.ensure_engine().say("继续计时")

    def _on_pomo_stop(self, sender, args):
        import pomodoro_util
        pomodoro_util.stop()
        eng = self.m.ensure_engine()
        eng.status_overlay = ""
        eng.quiet = False
        eng.say("番茄钟已结束")

    def _apply_size(self, label):
        from System.Drawing import Size

        eng = self.m.ensure_engine()
        if not eng.set_size(label):
            return
        self.m.meta_set("pet_size", eng.size_label)
        self.sprites = self._load_sprites(eng)
        if self.form:
            self.form.Size = Size(int(eng.win_w), int(eng.win_h))
            self._sync_form_pos(eng)
            enable_layered(self._hwnd())
        self._paint(eng)

    def apply_pet_settings(self, settings):
        """在 WinForms UI 线程中一次性应用面板保存的桌宠设置。"""
        settings = settings or {}
        eng = self.m.ensure_engine()
        eng.set_mode(settings.get("pet_mode", eng.mode))
        eng.set_speech_level(settings.get("pet_speech", eng.speech_level))
        eng.set_custom_lines(settings.get("pet_lines", eng.custom_lines))
        old_pack = eng.pet_pack_id
        eng.set_pet_pack(settings.get("pet_pack", old_pack))
        size = settings.get("pet_size", eng.size_label)
        if size != eng.size_label:
            self._apply_size(size)
        else:
            if eng.pet_pack_id != old_pack:
                self.sprites = self._load_sprites(eng)
            self._paint(eng)

    def _snap(self):
        eng = self.m.ensure_engine()
        hwnd = self._hwnd()
        eng.work = self.m.logical_work_area(hwnd)
        eng.snap()
        self._sync_form_pos(eng)
        self.m.meta_set("pet_x", int(eng.x))
        self.m.meta_set("pet_y", int(eng.y))

    def _sync_form_pos(self, eng):
        from System.Drawing import Point

        if not self.form:
            return
        px, py = self.m.logical_to_physical(eng.x, eng.y, self._hwnd())
        self.form.Location = Point(int(px), int(py))

    def _on_tick(self, sender, args):
        m = self.m
        if m._state.get("exiting") or not self.form:
            return
        eng = m.ensure_engine()
        self._tick_pomodoro(eng)
        if not self.form.Visible:
            return
        hwnd = self._hwnd()
        m._state["pet_hwnd"] = hwnd
        now = __import__("time").time()
        if now - self._work_ts > 1:
            self._work_ts = now
            eng.work = m.logical_work_area(hwnd)
        eng.away = m.live_away()
        cursor = m.cursor_logical(hwnd) if eng.mode == "follow" and not eng.dragging else None
        events = eng.tick(cursor=cursor)
        if events.get("pos") and not eng.dragging:
            self._sync_form_pos(eng)
            if now - self._last_save > 12:
                self._last_save = now
                m.meta_set("pet_x", int(eng.x))
                m.meta_set("pet_y", int(eng.y))
        self._paint(eng)

    def _paint(self, eng):
        if not self.form:
            return
        frame = compose_frame(eng, self.sprites)
        hwnd = self._hwnd()
        scale = self.m.dpi_scale(hwnd)
        if scale > 1.01:
            pw = max(1, int(round(frame.width * scale)))
            ph = max(1, int(round(frame.height * scale)))
            frame = frame.resize((pw, ph), Image.LANCZOS)
        blit_layered(hwnd, frame)

    def _on_down(self, sender, e):
        from System.Windows.Forms import Cursor, MouseButtons

        if e.Button != MouseButtons.Left:
            return
        self._press = Cursor.Position
        self._offset = None
        self._moved = False
        self.m.ensure_engine().on_drag_start()

    def _on_move(self, sender, e):
        from System.Drawing import Point
        from System.Windows.Forms import Control, Cursor, MouseButtons

        if self._press is None or Control.MouseButtons != MouseButtons.Left:
            return
        pos = Cursor.Position
        dx = pos.X - self._press.X
        dy = pos.Y - self._press.Y
        if not self._moved and abs(dx) + abs(dy) <= 6:
            return
        if not self._moved:
            self._moved = True
            loc = self.form.Location
            self._offset = Point(self._press.X - loc.X, self._press.Y - loc.Y)
        if self._offset is None:
            return
        self.form.Location = Point(pos.X - self._offset.X, pos.Y - self._offset.Y)
        eng = self.m.ensure_engine()
        if abs(dx) > 10:
            eng._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
        hwnd = self._hwnd()
        lx, ly = self.m.physical_to_logical(self.form.Location.X, self.form.Location.Y, hwnd)
        eng.x, eng.y = float(lx), float(ly)
        self._paint(eng)

    def _on_up(self, sender, e):
        from System.Windows.Forms import MouseButtons

        if e.Button != MouseButtons.Left:
            return
        eng = self.m.ensure_engine()
        eng.on_drag_end(self._moved)
        self._press = None
        self._offset = None
        if self._moved:
            hwnd = self._hwnd()
            lx, ly = self.m.physical_to_logical(self.form.Location.X, self.form.Location.Y, hwnd)
            eng.x, eng.y = float(lx), float(ly)
            self.m.meta_set("pet_x", int(eng.x))
            self.m.meta_set("pet_y", int(eng.y))
        else:
            eng.on_click()
        self._moved = False
        self._paint(eng)

    def _on_closing(self, sender, e):
        if self.m._state.get("exiting"):
            return
        user_close = False
        try:
            from System.Windows.Forms import CloseReason
            user_close = e.CloseReason == CloseReason.UserClosing
        except Exception:
            user_close = "UserClosing" in str(getattr(e, "CloseReason", ""))
        if not user_close:
            return
        e.Cancel = True
        self.hide()
        self.m.meta_set("show_pet", "0")

    def show(self):
        if self.form:
            self.form.Show()
            self.form.TopMost = True
            enable_layered(self._hwnd())
            self._paint(self.m.ensure_engine())

    def hide(self):
        if self.form:
            self.form.Hide()

    def close(self):
        if self.timer:
            try:
                self.timer.Stop()
            except Exception:
                pass
        if self.form:
            try:
                self.form.Close()
            except Exception:
                pass

    def visible(self):
        try:
            return bool(self.form and self.form.Visible)
        except Exception:
            return False
