"""播放调度引擎：后台线程按真实时间发送键鼠事件。

时间模型：事件表使用「音乐时间」（秒，与速度无关）。工作线程按 speed 把流逝的
物理时间积分成音乐时间，因此 speed 可实时改、进度可 seek、可在播放中换谱（实时移调）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import input_sender as isnd
from note_mapper import MappedNote, Slot, describe

# ---- 事件类型 ----
K_KEY = 0
K_MOUSE_LEFT = 1
K_MOUSE_RIGHT = 2
K_MOUSE_MIDDLE = 3

# 单音重触发最小间隔（同键连音必须先抬起再按下）
_MIN_RETRIGGER = 0.012
# 修饰键提前量
_SLOT_LEAD = 0.012
_SHARP_LEAD = 0.008
_SLOT_RELEASE_LEAD = 0.016


@dataclass
class PhysEvent:
    """一个物理键鼠事件（时间为音乐时间秒，与速度无关）。"""
    t: float
    kind: int
    code: str
    down: bool
    label: str = ""


def _build_schedule(notes: list[MappedNote]) -> tuple[list[PhysEvent], float]:
    """把主旋律音符压成物理键鼠事件表。返回 (events, 总音乐时长秒)。

    精确模式：无抖动、无乐句停顿。每个音严格按 MIDI 时间触发。
    单音策略：同键重叠时短暂抬起重触发；跨键重叠切断前音。
    """
    if not notes:
        return [], 0.0

    in_range = [n for n in notes if n.in_range]
    ordered = sorted(in_range, key=lambda n: (n.start, n.end))
    if not ordered:
        return [], 0.0

    evs: list[PhysEvent] = []
    held_key: str | None = None
    held_down_t = 0.0
    held_up_t = 0.0
    last_release: dict[str, float] = {}
    held_slot = Slot.MID
    held_sharp = False

    for n in ordered:
        t = max(0.0, n.start)
        t_end = max(t + 0.02, n.end)

        # 抬起上一个音
        if held_key is not None:
            up_t = held_up_t
            if up_t > t:
                up_t = t - 0.02
            if up_t < held_down_t + 0.01:
                up_t = held_down_t + 0.01
            evs.append(PhysEvent(up_t, K_KEY, held_key, False))
            last_release[held_key] = up_t
            held_key = None

        # 同键连音的最小重触发间隔
        down_t = t
        lu = last_release.get(n.key)
        if lu is not None and down_t < lu + _MIN_RETRIGGER:
            down_t = lu + _MIN_RETRIGGER

        # 八度档位切换（鼠标左/右键）
        if n.slot != held_slot:
            if held_slot == Slot.LOW:
                evs.append(PhysEvent(down_t - _SLOT_RELEASE_LEAD, K_MOUSE_LEFT, " ", False))
            elif held_slot == Slot.HIGH:
                evs.append(PhysEvent(down_t - _SLOT_RELEASE_LEAD, K_MOUSE_RIGHT, " ", False))
            if n.slot == Slot.LOW:
                evs.append(PhysEvent(down_t - _SLOT_LEAD, K_MOUSE_LEFT, " ", True))
            elif n.slot == Slot.HIGH:
                evs.append(PhysEvent(down_t - _SLOT_LEAD, K_MOUSE_RIGHT, " ", True))
            held_slot = n.slot

        # 升半音切换（鼠标中键）
        if n.sharp != held_sharp:
            evs.append(PhysEvent(down_t - _SHARP_LEAD, K_MOUSE_MIDDLE, " ", n.sharp))
            held_sharp = n.sharp

        evs.append(PhysEvent(down_t, K_KEY, n.key, True, describe(n)))
        held_key = n.key
        held_down_t = down_t
        held_up_t = t_end

    if held_key is not None:
        up_t = max(held_up_t, held_down_t + 0.01)
        evs.append(PhysEvent(up_t, K_KEY, held_key, False))

    # 夹掉负时间并排序
    for e in evs:
        if e.t < 0:
            e.t = 0.0
    evs.sort(key=lambda e: e.t)
    total = evs[-1].t if evs else 0.0
    return evs, total


class PlaybackEngine:
    def __init__(self):
        self._gate = threading.RLock()
        self._events: list[PhysEvent] = []
        self._total_music = 0.0
        self._speed = 1.0

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._resume = threading.Event()
        self._resume.set()
        self._cancel = threading.Event()

        self._music_now = 0.0
        self._last_phys = 0.0
        self._next_idx = 0
        self._t0 = 0.0
        self._manual_stop = False

        # UI 快照
        self._snap_elapsed = 0.0
        self._snap_total = 0.0
        self._snap_note = ""

        # 回调（在工作线程触发，UI 需自行 marshal 到主线程）
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_note: Optional[Callable[[str], None]] = None
        self.on_finished: Optional[Callable[[], None]] = None

    # ---- 只读快照 ----
    @property
    def elapsed(self) -> float:
        return self._snap_elapsed

    @property
    def total(self) -> float:
        return self._snap_total

    @property
    def current_note(self) -> str:
        return self._snap_note

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, v: float) -> None:
        self._speed = max(0.1, min(v, 5.0))

    def _clock(self) -> float:
        return time.perf_counter() - self._t0

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(msg)

    def _set_note(self, label: str) -> None:
        self._snap_note = label
        if self.on_note:
            self.on_note(label)

    # ---- 控制 ----
    def play(self, notes: list[MappedNote], speed: float) -> None:
        with self._gate:
            if self._running:
                self._stop_internal()
            self._speed = 1.0 if speed <= 0 else max(0.1, min(speed, 5.0))
            self._manual_stop = False
            self._set_note("")

            self._events, self._total_music = _build_schedule(notes)
            self._snap_total = self._total_music
            self._music_now = 0.0
            self._next_idx = 0
            in_range = sum(1 for n in notes if n.in_range)
            self._log(f"开始播放：共 {in_range} 个可演奏音符，总时长 ≈ {self._total_music:.1f}s")

            self._running = True
            self._paused = False
            self._resume.set()
            self._cancel.clear()
            self._t0 = time.perf_counter()
            self._last_phys = 0.0
            self._thread = threading.Thread(target=self._worker, name="PlaybackWorker", daemon=True)
            self._thread.start()

    def update_notes(self, notes: list[MappedNote]) -> None:
        """播放中更换剩余音符（实时移调）。"""
        with self._gate:
            if not self._running:
                return
            isnd.release_everything()
            self._set_note("")
            evs, total = _build_schedule(notes)
            self._events = evs
            if total > 0:
                self._total_music = max(self._total_music, total)
            self._next_idx = self._find_next_idx(self._music_now)
            self._log(f"已应用移调：剩余 {sum(1 for n in notes if n.in_range)} 音")

    def seek_fraction(self, fraction: float) -> None:
        with self._gate:
            if not self._running:
                return
            isnd.release_everything()
            self._set_note("")
            self._music_now = max(0.0, min(fraction, 1.0)) * self._total_music
            self._next_idx = self._find_next_idx(self._music_now)
            self._snap_elapsed = self._music_now

    def pause(self) -> None:
        with self._gate:
            if not self._running or self._paused:
                return
            self._paused = True
            self._resume.clear()
        isnd.release_everything()
        self._set_note("")
        self._log("已暂停。")

    def resume(self) -> None:
        with self._gate:
            if not self._running or not self._paused:
                return
            self._paused = False
            self._resume.set()
        self._log("继续播放。")

    def stop(self) -> None:
        with self._gate:
            self._manual_stop = True
            self._running = False
            self._resume.set()
            self._cancel.set()
        isnd.release_everything()
        self._set_note("")

    def _stop_internal(self) -> None:
        self._manual_stop = True
        self._running = False
        self._resume.set()
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        isnd.release_everything()
        self._set_note("")

    # ---- 工作线程 ----
    def _worker(self) -> None:
        try:
            while self._running:
                if self._paused:
                    self._resume.wait()
                    self._last_phys = self._clock()
                    continue

                now = self._clock()
                dt = now - self._last_phys
                self._last_phys = now
                if dt > 0:
                    self._music_now += dt * self._speed

                # 派发到期事件
                while (self._running and self._next_idx < len(self._events)
                       and self._events[self._next_idx].t <= self._music_now):
                    ev = self._events[self._next_idx]
                    self._execute(ev)
                    if ev.kind == K_KEY:
                        if ev.down:
                            self._set_note(ev.label)
                        elif (self._next_idx + 1 >= len(self._events)
                              or self._events[self._next_idx + 1].t > ev.t):
                            self._set_note("")
                    self._next_idx += 1

                # 结束判定
                if self._next_idx >= len(self._events):
                    slack = self._total_music + 0.25
                    if self._music_now < slack:
                        self._sleep_until(slack)
                        continue
                    break

                self._snap_elapsed = self._music_now
                self._snap_total = self._total_music

                # 睡到下一个事件
                next_t = self._events[self._next_idx].t
                if self._music_now < next_t:
                    remain_ms = (next_t - self._music_now) / self._speed * 1000.0
                    if remain_ms > 8:
                        self._cancel.wait(min(remain_ms - 4, 45) / 1000.0)
                    elif remain_ms > 1.5:
                        self._cancel.wait(0.001)
                    else:
                        while (self._running and not self._paused
                               and self._music_now < next_t - 0.0004):
                            t2 = self._clock()
                            d2 = t2 - self._last_phys
                            self._last_phys = t2
                            if d2 > 0:
                                self._music_now += d2 * self._speed
        finally:
            self._running = False
            isnd.release_everything()
            self._set_note("")
            self._snap_elapsed = min(self._snap_elapsed, self._total_music)
            if not self._manual_stop:
                if self.on_finished:
                    self.on_finished()
            else:
                self._snap_elapsed = 0.0

    def _sleep_until(self, until_music: float) -> None:
        start = time.perf_counter()
        while (self._running and not self._paused and not self._cancel.is_set()
               and self._music_now < until_music and time.perf_counter() - start < 60):
            now = self._clock()
            dt = now - self._last_phys
            self._last_phys = now
            if dt > 0:
                self._music_now += dt * self._speed
            self._cancel.wait(0.002)

    def _find_next_idx(self, music_now: float) -> int:
        floor = music_now - 0.06
        idx = 0
        while idx < len(self._events) and self._events[idx].t <= floor:
            idx += 1
        return idx

    @staticmethod
    def _execute(ev: PhysEvent) -> None:
        if ev.kind == K_KEY:
            (isnd.key_down if ev.down else isnd.key_up)(ev.code)
        elif ev.kind == K_MOUSE_LEFT:
            (isnd.mouse_down if ev.down else isnd.mouse_up)(isnd.MOUSE_LEFT)
        elif ev.kind == K_MOUSE_RIGHT:
            (isnd.mouse_down if ev.down else isnd.mouse_up)(isnd.MOUSE_RIGHT)
        elif ev.kind == K_MOUSE_MIDDLE:
            (isnd.mouse_down if ev.down else isnd.mouse_up)(isnd.MOUSE_MIDDLE)
