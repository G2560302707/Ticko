# -*- coding: utf-8 -*-
"""本地桌宠角色素材包：安全路径、PNG 校验、目录扫描与保存。"""
import io
import json
import os
import re
import shutil
import uuid

from PIL import Image


PACK_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
KINDS = ("front", "side", "back")
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PACK_BYTES = 30 * 1024 * 1024
MIN_SIDE = 24
MAX_SIDE = 4096


def safe_pack_dir(root, pack_id):
    if not PACK_ID_RE.match(pack_id or ""):
        return None
    root_abs = os.path.abspath(root)
    path = os.path.abspath(os.path.join(root_abs, pack_id))
    if path != root_abs and not path.startswith(root_abs + os.sep):
        return None
    return path


def safe_pack_file(root, pack_id, filename):
    if filename not in ("pack.json", "front.png", "side.png", "back.png"):
        return None
    folder = safe_pack_dir(root, pack_id)
    if not folder:
        return None
    return os.path.join(folder, filename)


def validate_png(payload):
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        return None, "图片为空"
    if len(payload) > MAX_IMAGE_BYTES:
        return None, "单张图片不能超过 12MB"
    try:
        with Image.open(io.BytesIO(payload)) as im:
            if im.format != "PNG":
                return None, "仅支持 PNG 图片"
            width, height = im.size
            im.verify()
    except Exception:
        return None, "PNG 文件损坏或无法读取"
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        return None, "图片尺寸需在 24–4096 像素之间"
    if width > height * 2.0:
        return None, "角色图片过宽，请使用单个角色立绘"
    return (int(width), int(height)), None


def pack_info(root, pack_id):
    folder = safe_pack_dir(root, pack_id)
    front = safe_pack_file(root, pack_id, "front.png")
    if not folder or not os.path.isdir(folder) or not front or not os.path.isfile(front):
        return None
    name = pack_id
    cfg = safe_pack_file(root, pack_id, "pack.json")
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            name = str(data.get("name") or pack_id).strip()[:40] or pack_id
    except Exception:
        pass
    kinds = [kind for kind in KINDS if os.path.isfile(safe_pack_file(root, pack_id, kind + ".png"))]
    return {
        "id": pack_id,
        "name": name,
        "builtin": False,
        "kinds": kinds,
        "preview": "/petpacks/%s/front.png" % pack_id,
    }


def list_packs(root):
    items = [{
        "id": "default",
        "name": "默认角色",
        "builtin": True,
        "kinds": list(KINDS),
        "preview": "/pet/sprites/front_187.png",
    }]
    if not os.path.isdir(root):
        return items
    for pack_id in sorted(os.listdir(root)):
        info = pack_info(root, pack_id)
        if info:
            items.append(info)
    return items


def normalize_selected(root, pack_id):
    if pack_id == "default":
        return "default"
    return pack_id if pack_info(root, pack_id) else "default"


def save_pack(root, name, images):
    images = images or {}
    front = images.get("front")
    if not front:
        return None, "正面立绘不能为空"
    total = sum(len(v) for v in images.values() if isinstance(v, (bytes, bytearray)))
    if total > MAX_PACK_BYTES:
        return None, "素材包不能超过 30MB"
    clean = {}
    for kind in KINDS:
        payload = images.get(kind)
        if not payload:
            continue
        _size, err = validate_png(payload)
        if err:
            return None, "%s：%s" % ({"front": "正面", "side": "侧面", "back": "背面"}[kind], err)
        clean[kind] = bytes(payload)
    pack_id = "p" + uuid.uuid4().hex[:12]
    folder = safe_pack_dir(root, pack_id)
    if not folder:
        return None, "无法创建素材包"
    display = " ".join(str(name or "自定义角色").strip().split())[:40] or "自定义角色"
    try:
        os.makedirs(folder, exist_ok=False)
        for kind, payload in clean.items():
            with open(os.path.join(folder, kind + ".png"), "wb") as f:
                f.write(payload)
        with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
            json.dump({"name": display, "format": 1}, f, ensure_ascii=False)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        return None, "保存素材包失败"
    return pack_info(root, pack_id), None


def delete_pack(root, pack_id):
    if pack_id == "default":
        return False
    folder = safe_pack_dir(root, pack_id)
    if not folder or not os.path.isdir(folder):
        return False
    shutil.rmtree(folder, ignore_errors=False)
    return not os.path.exists(folder)
