# -*- coding: utf-8 -*-
"""桌宠弹出的本地小窗：每日目标、番茄钟时间。"""
import goals_util
import pomodoro_util

GOAL_ROWS = (("active", "活跃"),) + tuple((name, name) for name in goals_util.CATEGORIES)


def _colors():
    from System.Drawing import Color
    return {
        # 与网页面板共用深石墨、青绿强调的语义，避免桌宠弹窗像另一套产品。
        "bg": Color.FromArgb(255, 23, 29, 36),
        "fg": Color.FromArgb(255, 243, 245, 247),
        "muted": Color.FromArgb(255, 152, 165, 181),
        "field": Color.FromArgb(255, 16, 20, 25),
        "btn": Color.FromArgb(255, 32, 40, 51),
        "line": Color.FromArgb(255, 43, 53, 65),
    }


def _font(size=10, bold=False):
    from System.Drawing import Font, FontStyle
    style = FontStyle.Bold if bold else FontStyle.Regular
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"):
        try:
            return Font(name, size, style)
        except Exception:
            continue
    return Font("Segoe UI", size, style)


def _paint_form(form, colors):
    from System.Windows.Forms import FormBorderStyle, FormStartPosition
    form.FormBorderStyle = getattr(FormBorderStyle, "FixedDialog")
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.ShowInTaskbar = False
    form.TopMost = True
    form.StartPosition = FormStartPosition.CenterScreen
    form.BackColor = colors["bg"]
    form.ForeColor = colors["fg"]
    try:
        form.Font = _font(10)
    except Exception:
        pass


def _label(form, text, x, y, w, colors, muted=False):
    from System.Windows.Forms import Label
    lab = Label()
    lab.Text = text
    lab.Left = x
    lab.Top = y
    lab.Width = w
    lab.Height = 22
    lab.ForeColor = colors["muted"] if muted else colors["fg"]
    form.Controls.Add(lab)
    return lab


def _button(form, text, x, y, w, colors, handler):
    from System.Windows.Forms import Button, FlatStyle
    btn = Button()
    btn.Text = text
    btn.Left = x
    btn.Top = y
    btn.Width = w
    btn.Height = 32
    btn.BackColor = colors["btn"]
    btn.ForeColor = colors["fg"]
    btn.FlatStyle = getattr(FlatStyle, "Flat")
    try:
        btn.FlatAppearance.BorderColor = colors["line"]
    except Exception:
        pass
    if handler:
        btn.Click += handler
    form.Controls.Add(btn)
    return btn


def _stepper(form, x, y, colors, initial=""):
    from System.Windows.Forms import Button, FlatStyle, TextBox, HorizontalAlignment, BorderStyle

    minus = Button()
    minus.Text = "−"
    minus.Left = x
    minus.Top = y
    minus.Width = 28
    minus.Height = 28
    minus.BackColor = colors["btn"]
    minus.ForeColor = colors["fg"]
    minus.FlatStyle = getattr(FlatStyle, "Flat")
    form.Controls.Add(minus)

    box = TextBox()
    box.Left = x + 30
    box.Top = y + 2
    box.Width = 88
    box.Height = 24
    box.Text = initial or ""
    box.BackColor = colors["field"]
    box.ForeColor = colors["fg"]
    try:
        box.BorderStyle = BorderStyle.FixedSingle
    except Exception:
        pass
    try:
        box.TextAlign = HorizontalAlignment.Center
    except Exception:
        pass
    form.Controls.Add(box)

    plus = Button()
    plus.Text = "+"
    plus.Left = x + 120
    plus.Top = y
    plus.Width = 28
    plus.Height = 28
    plus.BackColor = colors["btn"]
    plus.ForeColor = colors["fg"]
    plus.FlatStyle = getattr(FlatStyle, "Flat")
    form.Controls.Add(plus)

    def _step(delta):
        def _h(sender, e):
            cur = goals_util.parse_duration_text(box.Text)
            nxt = goals_util.step_duration(cur, delta)
            box.Text = goals_util.format_duration_short(nxt) if nxt else ""
        return _h

    minus.Click += _step(-5)
    plus.Click += _step(5)
    return box


def _store():
    try:
        import app as usage
        return usage.Handler.store
    except Exception:
        return None


def show_goals_dialog(owner=None):
    from System.Drawing import Size
    from System.Windows.Forms import DialogResult, Form

    store = _store()
    colors = _colors()
    form = Form()
    form.Text = "今日目标"
    form.ClientSize = Size(470, 430)
    _paint_form(form, colors)
    _label(form, "留空表示不启用。可手输 90、1:30、1h30，按钮每次加减 5 分钟。", 16, 12, 440, colors, muted=True)
    _label(form, "至少", 118, 40, 80, colors, muted=True)
    _label(form, "至多", 276, 40, 80, colors, muted=True)

    goals = goals_util.normalize_daily_goals(store.daily_goals() if store else None)
    boxes = {}
    y = 64
    for key, label in GOAL_ROWS:
        _label(form, label, 16, y + 4, 70, colors)
        pair = goals["active"] if key == "active" else goals["categories"].get(key) or {}
        mn = _stepper(form, 90, y, colors, goals_util.format_duration_short(pair.get("min")))
        mx = _stepper(form, 268, y, colors, goals_util.format_duration_short(pair.get("max")))
        boxes[key] = (mn, mx)
        y += 38

    saved = {"ok": False}

    def _pair(box_min, box_max):
        a = goals_util.parse_duration_text(box_min.Text)
        b = goals_util.parse_duration_text(box_max.Text)
        if a is not None and a <= 0:
            a = None
        if b is not None and b <= 0:
            b = None
        return {"min": a, "max": b}

    def on_save(sender, e):
        if not store:
            form.DialogResult = getattr(DialogResult, "Cancel")
            form.Close()
            return
        categories = {}
        for key, _label_name in GOAL_ROWS:
            if key == "active":
                continue
            categories[key] = _pair(*boxes[key])
        payload = {"active": _pair(*boxes["active"]), "categories": categories}
        store.save_daily_goals(payload)
        saved["ok"] = True
        form.DialogResult = getattr(DialogResult, "OK")
        form.Close()

    def on_cancel(sender, e):
        form.DialogResult = getattr(DialogResult, "Cancel")
        form.Close()

    _button(form, "保存", 250, 382, 90, colors, on_save)
    _button(form, "取消", 350, 382, 90, colors, on_cancel)
    try:
        form.ShowDialog(owner) if owner else form.ShowDialog()
    except Exception:
        form.ShowDialog()
    try:
        form.Dispose()
    except Exception:
        pass
    return saved["ok"]


def show_pomodoro_dialog(owner=None):
    from System.Drawing import Size
    from System.Windows.Forms import DialogResult, Form, TextBox

    store = _store()
    colors = _colors()
    form = Form()
    form.Text = "番茄钟时间"
    form.ClientSize = Size(360, 210)
    _paint_form(form, colors)
    _label(form, "专注和休息分钟，全部本机计时，不联网。", 16, 12, 330, colors, muted=True)
    focus, brk = pomodoro_util.load_from_store(store)
    _label(form, "专注（分钟）", 16, 48, 120, colors)
    _label(form, "休息（分钟）", 16, 92, 120, colors)

    def _num(x, y, value):
        box = TextBox()
        box.Left = x
        box.Top = y
        box.Width = 120
        box.Text = str(value)
        box.BackColor = colors["field"]
        box.ForeColor = colors["fg"]
        form.Controls.Add(box)
        return box

    focus_box = _num(150, 46, focus)
    break_box = _num(150, 90, brk)
    result = {"ok": False, "start": False}

    def _read():
        return pomodoro_util.save_to_store(store, focus_box.Text, break_box.Text)

    def on_save(sender, e):
        _read()
        result["ok"] = True
        form.DialogResult = getattr(DialogResult, "OK")
        form.Close()

    def on_start(sender, e):
        f, b = _read()
        pomodoro_util.start(f, b)
        result["ok"] = True
        result["start"] = True
        form.DialogResult = getattr(DialogResult, "OK")
        form.Close()

    def on_cancel(sender, e):
        form.DialogResult = getattr(DialogResult, "Cancel")
        form.Close()

    _button(form, "保存并开始", 16, 150, 110, colors, on_start)
    _button(form, "保存", 140, 150, 90, colors, on_save)
    _button(form, "取消", 244, 150, 90, colors, on_cancel)
    try:
        form.ShowDialog(owner) if owner else form.ShowDialog()
    except Exception:
        form.ShowDialog()
    try:
        form.Dispose()
    except Exception:
        pass
    return result
