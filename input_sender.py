"""通过 Windows SendInput 模拟键盘与鼠标（扫描码模式）。

使用 ctypes 直接调用 Windows user32.SendInput。
一律以「扫描码」发送按键（wVk=0 + KEYEVENTF_SCANCODE），大多数游戏/DirectInput
只认扫描码，兼容性最好、受输入法干扰最小。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

# ---- 平台判断：仅 Windows 真正发送输入，其它平台所有函数变成空操作，方便在别处 import ----
IS_WINDOWS = sys.platform == "win32"

# ---- 常量 ----
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

MAPVK_VK_TO_VSC = 0
VK_OEM_COMMA = 0xBC

# 鼠标按键标识
MOUSE_LEFT = "left"
MOUSE_RIGHT = "right"
MOUSE_MIDDLE = "middle"


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    wintypes.ULONG_PTR = wintypes.WPARAM  # SendInput 结构里的 dwExtraInfo

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", wintypes.ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", wintypes.ULONG_PTR),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.WORD

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int


def _vk_of(ch: str) -> int:
    """把演奏字符转成虚拟键码：A..Z 及键盘逗号','（高高音 do）。"""
    ch = ch.upper()
    if "A" <= ch <= "Z":
        return ord(ch)
    if ch == ",":
        return VK_OEM_COMMA
    return 0


def _send_key(ch: str, down: bool) -> None:
    if not IS_WINDOWS:
        return
    vk = _vk_of(ch)
    if vk == 0:
        return
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    inp = INPUT(type=INPUT_KEYBOARD,
                u=_INPUTunion(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags,
                                            time=0, dwExtraInfo=0)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _send_mouse(button: str, down: bool) -> None:
    if not IS_WINDOWS:
        return
    if button == MOUSE_LEFT:
        flag = MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
    elif button == MOUSE_RIGHT:
        flag = MOUSEEVENTF_RIGHTDOWN if down else MOUSEEVENTF_RIGHTUP
    else:
        flag = MOUSEEVENTF_MIDDLEDOWN if down else MOUSEEVENTF_MIDDLEUP
    inp = INPUT(type=INPUT_MOUSE,
                u=_INPUTunion(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag,
                                            time=0, dwExtraInfo=0)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def key_down(ch: str) -> None:
    _send_key(ch, True)


def key_up(ch: str) -> None:
    _send_key(ch, False)


def mouse_down(button: str) -> None:
    _send_mouse(button, True)


def mouse_up(button: str) -> None:
    _send_mouse(button, False)


# 演奏用到的全部键盘键（Z..M 和逗号）
PLAYABLE_KEYS = "ZXCVBNM,"


def release_everything() -> None:
    """把所有可能按下的键/鼠标键抬起，用于停止/暂停时清理状态。"""
    if not IS_WINDOWS:
        return
    for ch in PLAYABLE_KEYS:
        key_up(ch)
    mouse_up(MOUSE_LEFT)
    mouse_up(MOUSE_RIGHT)
    mouse_up(MOUSE_MIDDLE)


def foreground_window():
    """当前前台窗口句柄。"""
    if not IS_WINDOWS:
        return 0
    return user32.GetForegroundWindow()


def foreground_window_title() -> str:
    """当前前台窗口标题（诊断按键发给了谁）。"""
    if not IS_WINDOWS:
        return ""
    h = user32.GetForegroundWindow()
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, buf, 512)
    return buf.value


def bring_to_foreground(hwnd) -> None:
    """把指定窗口置前（停止时把焦点还给游戏后再补发一次“松开”）。"""
    if IS_WINDOWS and hwnd:
        user32.SetForegroundWindow(hwnd)
