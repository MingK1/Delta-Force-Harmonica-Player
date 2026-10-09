"""全局热键：低层键盘钩子（WH_KEYBOARD_LL），游戏中也能触发。

在独立线程里装钩子并跑消息循环。回调在该线程触发，UI 需自行 marshal。
识别按下的自定义热键（默认 F6/F7/F8/F9，支持 F1-F12、0-9、A-Z），
只拦截「按键松开」边沿触发一次，避免长按连发。并过滤合成按键，避免引擎自身发键误触发。
"""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"

WH_KEYBOARD_LL = 13
WM_KEYUP = 0x0101
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x10  # 合成按键（SendInput）标志位，用于过滤引擎自身发出的键

# 可自定义的虚拟键码：F1-F12、数字 0-9、字母 A-Z
VK_NAME_TO_CODE: dict[str, int] = {}
VK_NAME_TO_CODE.update({f"F{i}": 0x70 + (i - 1) for i in range(1, 13)})  # F1..F12
VK_NAME_TO_CODE.update({str(i): 0x30 + i for i in range(10)})             # 0..9
VK_NAME_TO_CODE.update({chr(0x41 + i): 0x41 + i for i in range(26)})      # A..Z
VK_CODE_TO_NAME = {v: k for k, v in VK_NAME_TO_CODE.items()}


class HotkeyManager:
    """管理一组全局热键：名字(如 'F6') -> 回调。"""

    def __init__(self):
        self._bindings: dict[int, Callable[[], None]] = {}
        self._name_by_code: dict[int, str] = {}
        self._thread: Optional[threading.Thread] = None
        self._hook = None
        self._thread_id = 0
        self._running = False
        # 必须持有引用，否则回调被 GC 后钩子崩溃
        self._proc = None

    def bind(self, key_name: str, callback: Callable[[], None]) -> bool:
        """绑定一个功能键。key_name 例如 'F6'；返回是否成功。"""
        code = VK_NAME_TO_CODE.get(key_name.upper())
        if code is None:
            return False
        self._bindings[code] = callback
        self._name_by_code[code] = key_name.upper()
        return True

    def clear(self) -> None:
        self._bindings.clear()
        self._name_by_code.clear()

    def start(self) -> None:
        if not IS_WINDOWS or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="HotkeyHook", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not IS_WINDOWS or not self._running:
            return
        self._running = False
        # 往钩子线程投递 WM_QUIT 让消息循环退出
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        # 显式声明签名：64 位下 wParam/lParam/返回值都是指针宽度，
        # 不声明会被当成 32 位 int 导致 OverflowError。
        user32.CallNextHookEx.restype = LRESULT
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int,
                                          wintypes.WPARAM, wintypes.LPARAM)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD),
                        ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        def low_level_proc(nCode, wParam, lParam):
            if nCode == 0 and wParam in (WM_KEYUP, WM_SYSKEYUP):
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                # 跳过合成按键（引擎用 SendInput 发的演奏键），避免与热键冲突
                if kb.flags & LLKHF_INJECTED:
                    return user32.CallNextHookEx(None, nCode, wParam, lParam)
                cb = self._bindings.get(kb.vkCode)
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._proc = HOOKPROC(low_level_proc)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)

        # 消息循环（钩子需要有消息泵）
        msg = wintypes.MSG()
        while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
