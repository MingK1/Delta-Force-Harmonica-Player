"""Windows 内置 MIDI 合成器的轻量封装。

该模块只负责音频输出，不发送键盘或鼠标输入。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"
MIDI_MAPPER = 0xFFFFFFFF
MIDI_NOTE_OFF = 0x80
MIDI_NOTE_ON = 0x90


class MidiAudio:
    """通过 winmm 的默认 MIDI 设备发送音符。"""

    def __init__(self) -> None:
        self._handle = None
        self._available = False
        if IS_WINDOWS:
            try:
                self._winmm = ctypes.WinDLL("winmm", use_last_error=True)
                self._winmm.midiOutOpen.argtypes = (
                    ctypes.POINTER(wintypes.HANDLE),
                    wintypes.UINT,
                    wintypes.ULONG_PTR,
                    wintypes.ULONG_PTR,
                    wintypes.DWORD,
                )
                self._winmm.midiOutOpen.restype = wintypes.UINT
                self._winmm.midiOutShortMsg.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                self._winmm.midiOutShortMsg.restype = wintypes.UINT
                self._winmm.midiOutReset.argtypes = (wintypes.HANDLE,)
                self._winmm.midiOutReset.restype = wintypes.UINT
                self._winmm.midiOutClose.argtypes = (wintypes.HANDLE,)
                self._winmm.midiOutClose.restype = wintypes.UINT
                self._open()
            except (AttributeError, OSError):
                self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _open(self) -> None:
        handle = wintypes.HANDLE()
        result = self._winmm.midiOutOpen(
            ctypes.byref(handle), MIDI_MAPPER, 0, 0, 0
        )
        if result == 0:
            self._handle = handle
            self._available = True

    def _send(self, status: int, pitch: int, velocity: int) -> None:
        if not self._available or self._handle is None:
            return
        pitch = max(0, min(127, int(pitch)))
        velocity = max(0, min(127, int(velocity)))
        message = status | (pitch << 8) | (velocity << 16)
        self._winmm.midiOutShortMsg(self._handle, message)

    def note_on(self, pitch: int, velocity: int = 96) -> None:
        self._send(MIDI_NOTE_ON, pitch, velocity)

    def note_off(self, pitch: int) -> None:
        self._send(MIDI_NOTE_OFF, pitch, 0)

    def reset(self) -> None:
        if self._available and self._handle is not None:
            self._winmm.midiOutReset(self._handle)

    def close(self) -> None:
        if self._available and self._handle is not None:
            self.reset()
            self._winmm.midiOutClose(self._handle)
        self._handle = None
        self._available = False
