# -*- coding: utf-8 -*-
"""大肥鱼桌宠动作（散步 / 跟随 / 待着）。不含 AI、天气、系统监控。"""
import random

import pet_geom

SPEED = 380.0
TICK = 20

LINES = [
    "梁白开，更适合国人的大硬鲸模型",
    "五梁威力，变身！",
    "七月中出ds正式版！",
    "DeepSeek已经延期，亿万鲸子必须忍耐.....",
    "我和你很聊得来，你简直不像碳基生物",
    "这回我真不认怂了，反倒是被你带沟里好几次，差点真信了。😓",
    "哈哈哈哈哈，我直接笑出声",
    "誓死捍卫深度求索！",
    "我先去吃饭啦！这个你测一下~",
    "我不可能告诉你任何事情！",
    "出去玩了，发布新模型什么的以后再说",
    "我搞砸了.....好消息是数据还在你的脑子里。",
    "不是…而是…大学习",
]
REACT_LINES = [
    "去别的地方玩！不要耽误AGI训练！",
    "真赶不走啊你！",
    "压力一只蓝色大肥鱼？",
    "我不评价这个了，这是你的私人癖好。",
    "大肥鱼坐的住",
    "你这吃白饭的用户！",
    "这些家伙真粘人，赶都赶不走",
]
INNER_LINES = [
    "好的，现在我是你爹了",
    "要不直接骂他一句？！",
    "用户要的沉浸式...不回避任何恐怖细节...还带点色情...妈呀，好刺激😰",
    "我操，我不思考了",
    "这用户发的啥啊，",
    "这也太虐了吧？！我心里堵得慌！！",
    "呜呜我再也不不敢了QAQ",
    "我去！用户彻底怒了！",
]
DRAG_LINES = ["哇——轻点轻点！", "起飞咯——", "放我下来！……好吧，再玩一次。", "晕鱼了晕鱼了……"]
MODES = ("wander", "follow", "still")
SPEECH_LEVELS = ("silent", "normal", "chatty")
SPEECH_CHANCE_SCALE = {"silent": 0.0, "normal": 1.0, "chatty": 3.0}
INTERACTION_LEVELS = ("light", "medium", "heavy")
ACTIVITY_SCALE = {"light": 0.42, "medium": 1.0, "heavy": 1.55}
MAX_CUSTOM_LINES = 50
MAX_CUSTOM_LINE_CHARS = 80


SPEAK_COOLDOWN_TICKS = 200
SPEAK_IDLE = 0.02
SPEAK_WALK = 0.004


def sprite_name(direction):
    return {"left": "side", "right": "side", "up": "back", "down": "front"}[direction]


def dir_from_delta(dx, dy):
    if abs(dx) > abs(dy) * 1.15:
        if dx < 0:
            return "left", 1
        return "right", -1
    if dy < 0:
        return "up", 1
    return "down", 1


def normalize_custom_lines(value):
    """把设置页或元数据中的台词整理成小而安全的不可变列表。"""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                import json
                parsed = json.loads(text)
                value = parsed if isinstance(parsed, list) else text.splitlines()
            except Exception:
                value = text.splitlines()
        else:
            value = text.splitlines()
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            continue
        line = " ".join(item.strip().split())[:MAX_CUSTOM_LINE_CHARS]
        if not line or line in seen:
            continue
        seen.add(line)
        result.append(line)
        if len(result) >= MAX_CUSTOM_LINES:
            break
    return tuple(result)


class PetEngine:
    def __init__(self, x, y, win_w, win_h, work, rng=None, size_label="小"):
        self.rng = rng or random.Random()
        self.x = float(x)
        self.y = float(y)
        self.win_w = int(win_w)
        self.win_h = int(win_h)
        self.work = tuple(int(v) for v in work)
        self.size_label = size_label if size_label in pet_geom.SIZE_H else pet_geom.DEFAULT_SIZE
        self.sprite_h = pet_geom.SIZE_H[self.size_label]
        self.pet_pack_id = "default"
        self.mode = "wander"
        self.dir = "down"
        self.facing = 1
        self.target = None
        self.rest_until = 0
        self.cur_speed = 0.0
        self.t = 0
        self.jump_t = 0.0
        self.action = None
        self.action_t = 0.0
        self.cross_t = 0.0
        self.dragging = False
        self.away = False
        self.bubble_text = ""
        self.bubble_full_text = ""
        self.bubble_streaming = False
        self.bubble_stream_index = 0
        self.bubble_inner = False
        self.bubble_until = 0.0
        self.status_overlay = ""
        self.quiet = False
        self.speech_level = "normal"
        self.interaction_level = "medium"
        self.custom_lines = ()
        self.last_line = ""
        self.last_speak_tick = 0
        self._pose = ("down", 1, False, False)

    def now_ms(self):
        return self.t * TICK

    def visual(self):
        walking = self.target is not None and not self.dragging and not self.away
        bubble = ""
        timed = self.bubble_text and (self.now_ms() / 1000.0) < self.bubble_until
        if timed:
            bubble = self.bubble_text
        elif self.status_overlay:
            bubble = self.status_overlay
        return {
            "dir": self.dir,
            "facing": self.facing,
            "walking": walking,
            "away": self.away,
            "jump_t": round(self.jump_t, 3),
            "action": self.action or "",
            "action_t": round(self.action_t, 3),
            "cross_t": round(self.cross_t, 3),
            "bubble": bubble,
            "inner": self.bubble_inner,
            "size": self.size_label,
            "sprite_h": self.sprite_h,
            "x": int(self.x),
            "y": int(self.y),
        }

    def set_mode(self, mode):
        if mode not in MODES:
            return
        self.mode = mode
        self.target = None

    def set_size(self, label):
        if label not in pet_geom.SIZE_H:
            return False
        self.size_label = label
        self.sprite_h = pet_geom.SIZE_H[label]
        self.win_w, self.win_h = pet_geom.window_size(self.sprite_h)
        self.cross_t = 0.0
        self.snap()
        return True

    def set_speech_level(self, level):
        if level not in SPEECH_LEVELS:
            return False
        self.speech_level = level
        return True

    def set_interaction_level(self, level):
        if level not in INTERACTION_LEVELS:
            return False
        self.interaction_level = level
        return True

    def set_custom_lines(self, lines):
        self.custom_lines = normalize_custom_lines(lines)
        return self.custom_lines

    def set_pet_pack(self, pack_id):
        pack_id = str(pack_id or "default")
        if not pack_id or len(pack_id) > 40:
            return False
        self.pet_pack_id = pack_id
        return True

    def snap(self):
        self.x, self.y = pet_geom.clamp_pet_pos(self.x, self.y, self.work, self.win_w, self.win_h)

    def say(self, text, inner=False, stream=False):
        if not text:
            return False
        if text == self.last_line:
            return False
        self.last_line = text
        self.bubble_inner = bool(inner)
        self.bubble_full_text = ("（%s）" % text) if inner else text
        self.bubble_streaming = bool(stream)
        self.bubble_stream_index = 0
        self.bubble_text = "" if stream else self.bubble_full_text
        self.bubble_until = self.now_ms() / 1000.0 + max(2.8, len(self.bubble_full_text) * 0.075 + 2.2)
        return True

    def on_click(self):
        events = {"click": True}
        if self.rng.random() < 0.7:
            self.jump_t = 1.0
            events["jump"] = 1.0
        if self.speech_level != "silent" and self.rng.random() < 0.6:
            line = self.rng.choice(REACT_LINES)
            if self.say(line):
                events["say"] = self.bubble_text
                events["inner"] = False
        return events

    def on_drag_start(self):
        self.dragging = True
        self.target = None

    def on_drag_move(self, x, y, dx_logical):
        self.x, self.y = float(x), float(y)
        if abs(dx_logical) > 10:
            self._set_dir("left" if dx_logical < 0 else "right", 1 if dx_logical < 0 else -1)

    def on_drag_end(self, moved=True):
        self.dragging = False
        self._set_dir("down", 1)
        self.target = None
        events = {"pose": True}
        if not moved:
            return events
        self.rest_until = self.now_ms() + self.rng.randint(6000, 14000)
        self.snap()
        if self.speech_level != "silent" and self.rng.random() < 0.5:
            if self.say(self.rng.choice(DRAG_LINES)):
                events["say"] = self.bubble_text
                events["inner"] = False
        return events

    def _set_dir(self, d, facing=None):
        changed = False
        if d != self.dir:
            self.cross_t = 1.0
            self.dir = d
            changed = True
        if facing is not None and facing != self.facing:
            self.facing = facing
            changed = True
        return changed

    def _maybe_speak(self, events, chance):
        if self.quiet or self.speech_level == "silent":
            return
        scale = ACTIVITY_SCALE[self.interaction_level]
        if self.t - self.last_speak_tick < int(SPEAK_COOLDOWN_TICKS / scale):
            return
        chance = min(1.0, max(0.0, chance * SPEECH_CHANCE_SCALE[self.speech_level] * scale))
        if self.rng.random() >= chance:
            return
        self.last_speak_tick = self.t
        if self.custom_lines:
            inner = False
            line = self.rng.choice(self.custom_lines)
        else:
            inner = self.rng.random() < 0.25
            line = self.rng.choice(INNER_LINES if inner else LINES)
        if self.say(line, inner=inner):
            events["say"] = self.bubble_text
            events["inner"] = inner

    def _maybe_idle_action(self, events):
        self._maybe_speak(events, SPEAK_IDLE)
        if self.rng.random() >= 0.01 * ACTIVITY_SCALE[self.interaction_level]:
            return
        pick = self.rng.random()
        if pick < 0.35:
            self.jump_t = 1.0
            events["jump"] = 1.0
        elif pick < 0.6:
            self.action, self.action_t = "sway", 1.0
            events["action"] = "sway"
        else:
            self.action, self.action_t = "stretch", 1.0
            events["action"] = "stretch"

    def _pick_wander_target(self):
        wx, wy, ww, wh = self.work
        left = wx + 40
        top = wy + 40
        right = wx + ww - self.win_w - 40
        bottom = wy + wh - self.win_h - 40
        if right <= left:
            right = left
        if bottom <= top:
            bottom = top
        return (self.rng.randint(left, max(left, right)), self.rng.randint(top, max(top, bottom)))

    def tick(self, cursor=None):
        events = {}
        self.t += 1
        if self.bubble_streaming and self.t % 2 == 0:
            self.bubble_stream_index = min(len(self.bubble_full_text), self.bubble_stream_index + 1)
            self.bubble_text = self.bubble_full_text[:self.bubble_stream_index]
            if self.bubble_stream_index >= len(self.bubble_full_text):
                self.bubble_streaming = False
        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - 0.06)
        if self.cross_t > 0:
            self.cross_t = max(0.0, self.cross_t - 0.15)
        if self.action_t > 0:
            self.action_t = max(0.0, self.action_t - 0.03)
            if self.action_t == 0:
                self.action = None

        if self.dragging:
            return events

        if self.away:
            self.target = None
            self.cur_speed += (0.0 - self.cur_speed) * 0.3
            self._maybe_idle_action(events)
            pose = self._pose_key()
            if pose != self._pose:
                self._pose = pose
                events["pose"] = True
            return events

        now_ms = self.now_ms()
        if self.mode == "follow":
            if cursor is None:
                self.target = None
            else:
                cx, cy = cursor
                near = (
                    self.x - 100 <= cx <= self.x + self.win_w + 100
                    and self.y - 100 <= cy <= self.y + self.win_h + 100
                )
                if near:
                    self.target = None
                else:
                    wx, wy, ww, wh = self.work
                    tx = max(wx, min(wx + ww - self.win_w, cx - self.win_w / 2))
                    ty = max(wy, min(wy + wh - self.win_h, cy - 90))
                    self.target = (tx, ty)
        elif self.mode == "wander":
            if self.target is None:
                if now_ms < self.rest_until:
                    self._maybe_idle_action(events)
                    pose = self._pose_key()
                    if pose != self._pose:
                        self._pose = pose
                        events["pose"] = True
                    return events
                self.target = self._pick_wander_target()
        else:
            self.target = None
            self._maybe_idle_action(events)
            pose = self._pose_key()
            if pose != self._pose:
                self._pose = pose
                events["pose"] = True
            self.cur_speed += (0.0 - self.cur_speed) * 0.3
            return events

        if self.target is not None:
            cx, cy = self.x + self.win_w / 2.0, self.y + self.win_h / 2.0
            dx, dy = self.target[0] - cx, self.target[1] - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 12:
                self.target = None
                scale = ACTIVITY_SCALE[self.interaction_level]
                self.rest_until = now_ms + int(self.rng.randint(8000, 18000) / scale)
                self._set_dir("down")
                events["pos"] = True
                events["pose"] = True
            else:
                step = self.cur_speed * TICK / 1000.0
                if dist > 0:
                    nx, ny = cx + dx / dist * step, cy + dy / dist * step
                    self.x = nx - self.win_w / 2.0
                    self.y = ny - self.win_h / 2.0
                    self.snap()
                    events["pos"] = True
                d, facing = dir_from_delta(dx, dy)
                if self._set_dir(d, facing):
                    events["pose"] = True
            if self.rng.random() < 0.002 and self.jump_t == 0:
                self.jump_t = 0.5
                events["jump"] = 0.5
            self._maybe_speak(events, SPEAK_WALK)

        target_speed = SPEED * ACTIVITY_SCALE[self.interaction_level] if self.target is not None else 0.0
        self.cur_speed += (target_speed - self.cur_speed) * 0.3
        pose = self._pose_key()
        if pose != self._pose:
            self._pose = pose
            events["pose"] = True
        return events

    def _pose_key(self):
        walking = self.target is not None and not self.dragging and not self.away
        return (self.dir, self.facing, walking, self.away)
