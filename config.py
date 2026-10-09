"""设置持久化：保存到 %LOCALAPPDATA%\\DFPlayer\\settings.json。

记住速度/移调/旋律模式/热键，下次启动恢复。
"""
from __future__ import annotations

import json
import os

from note_mapper import MelodyMode
from player import PlayOptions

APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                       "DFPlayer")
CONFIG_PATH = os.path.join(APP_DIR, "settings.json")

DEFAULT_HOTKEYS = {
    "play_pause": "F6",
    "prev": "F7",
    "next": "F8",
    "stop": "F9",
}


def _defaults() -> dict:
    return {
        "speed": 1.0,
        "transpose": 0,
        "trim_leading": True,
        "melody_mode": MelodyMode.RAW.name,
        "hotkeys": dict(DEFAULT_HOTKEYS),
        "midi_dir": "",
        "song_settings": {},   # {relative_path: {part, speed, melody_mode}, ...}
    }


def load() -> dict:
    data = _defaults()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            return data
        for key in data:
            if key in saved:
                data[key] = saved[key]
        if not isinstance(data["midi_dir"], str):
            data["midi_dir"] = ""
        if not isinstance(data["song_settings"], dict):
            data["song_settings"] = {}
        else:
            data["song_settings"] = {
                key: value for key, value in data["song_settings"].items()
                if isinstance(key, str) and isinstance(value, dict)
            }
        if isinstance(saved.get("hotkeys"), dict):
            data["hotkeys"] = {
                **DEFAULT_HOTKEYS,
                **{k: v for k, v in saved["hotkeys"].items()
                   if isinstance(k, str) and isinstance(v, str)},
            }
        else:
            data["hotkeys"] = dict(DEFAULT_HOTKEYS)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        pass
    return data


def save(data: dict) -> None:
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def apply_to_options(data: dict) -> PlayOptions:
    """把配置字典转成 PlayOptions。"""
    if not isinstance(data, dict):
        data = _defaults()
    try:
        melody_mode = MelodyMode[data.get("melody_mode", MelodyMode.RAW.name)]
    except (KeyError, TypeError):
        melody_mode = MelodyMode.RAW

    speed = data.get("speed", 1.0)
    if not isinstance(speed, (int, float)) or isinstance(speed, bool):
        speed = 1.0
    transpose = data.get("transpose", 0)
    if not isinstance(transpose, int) or isinstance(transpose, bool):
        transpose = 0
    trim_leading = data.get("trim_leading", True)
    if not isinstance(trim_leading, bool):
        trim_leading = True
    return PlayOptions(
        speed=float(speed),
        transpose=transpose,
        trim_leading=trim_leading,
        melody_mode=melody_mode,
    )
