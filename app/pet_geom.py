# -*- coding: utf-8 -*-
"""桌宠窗口尺寸与坐标。move() 使用逻辑像素。"""

SIZE_H = {"小": 187, "中": 238, "大": 306}
SPRITE_MAX_W = {187: 140, 238: 178, 306: 229}
MARGIN = 2
DEFAULT_SIZE = "小"


def bubble_font_px(sprite_h):
    return max(15, int(round(int(sprite_h) * 0.088)))


def bubble_metrics(sprite_h):
    """气泡随立绘身高缩放：约 14 个汉字宽、最多 3 行，保证原版台词能显示全。"""
    font = bubble_font_px(sprite_h)
    line_h = int(round(font * 1.42))
    pad_x = max(10, int(round(font * 0.72)))
    pad_y = max(8, int(round(font * 0.48)))
    tail = max(8, int(round(font * 0.5)))
    max_text_w = int(round(font * 14.5))
    band_w = max_text_w + pad_x * 2
    band_h = line_h * 3 + pad_y * 2 + tail + 8
    return {
        "font": font,
        "line_h": line_h,
        "pad_x": pad_x,
        "pad_y": pad_y,
        "tail": tail,
        "max_text_w": max_text_w,
        "band_w": band_w,
        "band_h": band_h,
    }


def window_size(sprite_h):
    h = int(sprite_h)
    mx = int(h * 0.062) + 6
    sprite_w = int(SPRITE_MAX_W.get(h, 140)) + mx * 2
    metrics = bubble_metrics(h)
    w = max(sprite_w, metrics["band_w"] + 12)
    return w, h + metrics["band_h"] + MARGIN * 2


PET_W, PET_H = window_size(SIZE_H[DEFAULT_SIZE])


def clamp_pet_pos(x, y, work, win_w=PET_W, win_h=PET_H, margin=8):
    wx, wy, ww, wh = [int(v) for v in work]
    min_x = wx + margin
    min_y = wy + margin
    max_x = wx + ww - int(win_w) - margin
    max_y = wy + wh - int(win_h) - margin
    if max_x < min_x:
        max_x = min_x
    if max_y < min_y:
        max_y = min_y
    return min(max(int(x), min_x), max_x), min(max(int(y), min_y), max_y)


def default_pet_pos_from_work(work, win_w=PET_W, win_h=PET_H):
    wx, wy, ww, wh = [int(v) for v in work]
    x = wx + ww - int(win_w) - 20
    y = wy + wh - int(win_h) - 40
    return clamp_pet_pos(x, y, work, win_w, win_h)


def rects_intersect(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by
