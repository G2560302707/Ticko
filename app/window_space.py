# -*- coding: utf-8 -*-
"""桌面空间纯数据模型（窗口攀爬 v1 的数据底座）。

设计约束（任务 A-1 / A-1R，不可违反）：
- 纯 Python、无 Windows API、无 UI 副作用、无持久化、无第三方依赖。
- 所有坐标视为宿主已统一转换过的逻辑坐标；本模块绝不处理 DPI。
- 不枚举真实窗口、不读取系统状态、不保存任何内容。
- 对空列表、None、异常输入必须保守处理，不抛未处理异常。
- 数据模型构造后真正不可变（含底层存储字段，赋值即抛 AttributeError）。
- 仅服务未来窗口攀爬，不改变当前宠物任何实际运行行为。
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple


class _Frozen:
    """构造后冻结所有属性赋值（含底层存储字段）的最小基类。

    仅用于满足“构造后真正不可变”的要求；不参与对外 API。
    """

    __slots__ = ("_frozen",)

    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False):
            raise AttributeError(
                "%s is immutable; cannot set %r" % (type(self).__name__, name))
        object.__setattr__(self, name, value)


# ---------------------------------------------------------------------------
# 不可变数据模型
# ---------------------------------------------------------------------------
class Rect(_Frozen):
    """一个矩形，坐标为宿主已统一转换过的逻辑坐标（本模块不处理 DPI）。"""

    __slots__ = ("_x", "_y", "_width", "_height")

    def __init__(self, x, y, width, height):
        self._x = int(x)
        self._y = int(y)
        self._width = int(width)
        self._height = int(height)
        self._frozen = True

    @property
    def x(self) -> int:
        return self._x

    @property
    def y(self) -> int:
        return self._y

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def right(self) -> int:
        return self._x + self._width

    @property
    def bottom(self) -> int:
        return self._y + self._height

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self._x, self._y, self._width, self._height)

    def __eq__(self, other) -> bool:
        if not isinstance(other, Rect):
            return NotImplemented
        return (self._x, self._y, self._width, self._height) == (
            other._x, other._y, other._width, other._height,
        )

    def __hash__(self) -> int:
        return hash((self._x, self._y, self._width, self._height))

    def __repr__(self) -> str:
        return "Rect(x=%d, y=%d, width=%d, height=%d)" % (
            self._x, self._y, self._width, self._height,
        )


class Monitor(_Frozen):
    """一个显示器。full_rect 为包含任务栏的完整屏幕，work_rect 为工作区。"""

    __slots__ = ("_handle", "_full_rect", "_work_rect", "_is_primary")

    def __init__(self, handle, full_rect: Rect, work_rect: Rect, is_primary: bool = False):
        self._handle = handle
        self._full_rect = full_rect
        self._work_rect = work_rect
        self._is_primary = bool(is_primary)
        self._frozen = True

    @property
    def handle(self):
        return self._handle

    @property
    def full_rect(self) -> Rect:
        return self._full_rect

    @property
    def work_rect(self) -> Rect:
        return self._work_rect

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    def __repr__(self) -> str:
        return "Monitor(handle=%r, is_primary=%r)" % (self._handle, self._is_primary)


class WindowInfo(_Frozen):
    """一个窗口的静态快照。可见性与 z-order 由宿主枚举后填入，本模块不查询。"""

    __slots__ = ("_handle", "_rect", "_is_foreground", "_is_visible")

    def __init__(self, handle, rect: Rect, is_foreground: bool = False, is_visible: bool = True):
        self._handle = handle
        self._rect = rect
        self._is_foreground = bool(is_foreground)
        self._is_visible = bool(is_visible)
        self._frozen = True

    @property
    def handle(self):
        return self._handle

    @property
    def rect(self) -> Optional[Rect]:
        return self._rect

    @property
    def is_foreground(self) -> bool:
        return self._is_foreground

    @property
    def is_visible(self) -> bool:
        return self._is_visible

    def __repr__(self) -> str:
        return "WindowInfo(handle=%r, is_foreground=%r, is_visible=%r)" % (
            self._handle, self._is_foreground, self._is_visible,
        )


class WindowSpace(_Frozen):
    """某一时刻的桌面空间快照：显示器集合、窗口集合、回退工作区。"""

    __slots__ = ("_monitors", "_windows", "_fallback_work_rect")

    def __init__(self, monitors: Optional[Sequence[Monitor]] = None,
                 windows: Optional[Sequence[WindowInfo]] = None,
                 fallback_work_rect: Optional[Rect] = None):
        self._monitors = tuple(monitors) if monitors is not None else ()
        self._windows = tuple(windows) if windows is not None else ()
        self._fallback_work_rect = fallback_work_rect
        self._frozen = True

    @property
    def monitors(self) -> Tuple[Monitor, ...]:
        return self._monitors

    @property
    def windows(self) -> Tuple[WindowInfo, ...]:
        return self._windows

    @property
    def fallback_work_rect(self) -> Optional[Rect]:
        return self._fallback_work_rect

    def __repr__(self) -> str:
        return "WindowSpace(monitors=%d, windows=%d)" % (
            len(self._monitors), len(self._windows),
        )


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
def _overlap_area(a: Optional[Rect], b: Optional[Rect]) -> int:
    """返回两个矩形交叠面积；任一为 None 或互不交叠则返回 0。"""
    if a is None or b is None:
        return 0
    try:
        ix = max(a.x, b.x)
        iy = max(a.y, b.y)
        ix2 = min(a.right, b.right)
        iy2 = min(a.bottom, b.bottom)
    except Exception:
        return 0
    w = ix2 - ix
    h = iy2 - iy
    if w <= 0 or h <= 0:
        return 0
    return w * h


# ---------------------------------------------------------------------------
# 纯几何 / 查询函数
# ---------------------------------------------------------------------------
def rect_contains(outer: Optional[Rect], inner: Optional[Rect]) -> bool:
    """outer 是否完全包含 inner（边沿相切视为包含）。任一为 None 返回 False。"""
    if outer is None or inner is None:
        return False
    try:
        return (outer.x <= inner.x and outer.y <= inner.y
                and outer.right >= inner.right and outer.bottom >= inner.bottom)
    except Exception:
        return False


def rect_intersects(a: Optional[Rect], b: Optional[Rect]) -> bool:
    """两矩形是否严格交叠（交叠面积 > 0；边沿相切面积为 0 视为不相交）。"""
    if a is None or b is None:
        return False
    try:
        return not (a.right <= b.x or b.right <= a.x
                    or a.bottom <= b.y or b.bottom <= a.y)
    except Exception:
        return False


def monitor_for_rect(monitors: Optional[Sequence[Monitor]], rect: Optional[Rect]):
    """按最大交叠面积选择显示器；无交叠时返回 primary；无显示器或 rect 为 None 返回 None。

    交叠面积并列时优先返回 primary 显示器，以保证结果确定。
    列表中存在 None、普通 object 或缺少 full_rect 的畸形项时，逐项跳过，
    不抛未处理异常；无任何合法显示器时返回 None。
    """
    if not monitors or rect is None:
        return None
    try:
        mon_list = list(monitors)
    except Exception:
        return None
    best = None
    best_area = -1
    for m in mon_list:
        try:
            area = _overlap_area(m.full_rect, rect)
        except Exception:
            # 畸形显示器（无 full_rect / 非 Monitor 等）：跳过
            continue
        if area > best_area:
            best = m
            best_area = area
        elif area == best_area and area > 0 and best is not None \
                and not best.is_primary and m.is_primary:
            # 并列时切换到 primary
            best = m
    if best_area > 0 and best is not None:
        return best
    # 无任何交叠：回退到 primary 显示器（若存在）
    for m in mon_list:
        try:
            if m.is_primary:
                return m
        except Exception:
            continue
    return None


def is_fullscreen_rect(window_rect: Optional[Rect], monitor_full_rect: Optional[Rect],
                       tolerance: int = 2) -> bool:
    """窗口四条边是否分别接近显示器四条边（即全屏）。

    必须四条边均在 tolerance 内对齐：abs(左差)、abs(上差)、abs(右差)、abs(下差)
    均 <= tolerance。仅“窗口位于显示器内部”不足以判定全屏。
    任一矩形为 None 返回 False；tolerance 为负时按 0 处理。
    """
    if window_rect is None or monitor_full_rect is None:
        return False
    try:
        t = tolerance if tolerance is not None else 0
        if t < 0:
            t = 0
        m = monitor_full_rect
        w = window_rect
        return (abs(w.x - m.x) <= t and abs(w.y - m.y) <= t
                and abs(w.right - m.right) <= t and abs(w.bottom - m.bottom) <= t)
    except Exception:
        return False


def valid_window_candidate(window: Optional[WindowInfo], pet_handle=None) -> bool:
    """判断窗口是否可作为攀爬/锚定的候选。

    过滤规则：不可见、自身（handle == pet_handle）、宽或高 < 80 的窗口。
    对 None 或属性缺失/异常一律返回 False，不抛未处理异常。
    """
    if window is None:
        return False
    try:
        if not window.is_visible:
            return False
        if pet_handle is not None and window.handle == pet_handle:
            return False
        rect = window.rect
        if rect is None:
            return False
        if rect.width < 80 or rect.height < 80:
            return False
        return True
    except Exception:
        return False
