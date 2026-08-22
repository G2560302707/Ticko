# -*- coding: utf-8 -*-
import os
import re

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm"}
THEME_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
FILE_RE = re.compile(r"^[a-zA-Z0-9._-]{1,80}$")
MAX_UPLOAD = 80 * 1024 * 1024


def safe_theme_path(root, theme_id, filename=None):
    if not THEME_ID_RE.match(theme_id or ""):
        return None
    base = os.path.abspath(os.path.join(root, theme_id))
    root_abs = os.path.abspath(root)
    if not base.startswith(root_abs + os.sep) and base != root_abs:
        return None
    if filename is None:
        return base
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    name = os.path.basename(filename)
    if not FILE_RE.match(name):
        return None
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT and name != "theme.json":
        return None
    path = os.path.abspath(os.path.join(base, name))
    if not path.startswith(base + os.sep):
        return None
    return path
