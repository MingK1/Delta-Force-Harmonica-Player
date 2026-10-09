"""音高 → 乐器按键的映射，以及主旋律的预处理（单音化、移调、去空拍）。

键位方案：
  一个八度 do..ti  → 键盘 Z X C V B N M
  升半音（#）      → 同时按住鼠标中键
  低八度           → 按住鼠标左键
  高八度           → 按住鼠标右键
  高高音 do/#do    → 键盘逗号','（配合右键，#do 再加中键）
可演奏范围：低音 do ~ 高高音 #do，超出的音自动空拍跳过。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


def _mod(a: int, m: int) -> int:
    return ((a % m) + m) % m


class Slot(IntEnum):
    """八度档位：相对基准八度的偏移。"""
    LOW = -1    # 低八度 → 鼠标左键
    MID = 0     # 基准八度 → 不按鼠标
    HIGH = 1    # 高八度 → 鼠标右键


class MelodyMode(Enum):
    """旋律提取模式。"""
    RAW = "原始音轨"       # 不处理，直接演奏选定声部的原始音符
    HIGHEST = "取最高音"    # 同刻多音取最高
    SKYLINE = "天际线"      # 追踪旋律线条连续性，适合多声部 MIDI


@dataclass
class RawNote:
    """MIDI 里的一个音符（时间单位：秒）。"""
    pitch: int
    start: float
    end: float
    velocity: int = 96


@dataclass
class MappedNote:
    """映射后的可演奏音符。"""
    pitch: int
    start: float
    end: float
    key: str = " "
    sharp: bool = False               # 需按住鼠标中键
    slot: Slot = Slot.MID
    in_range: bool = True             # False → 超范围，空拍跳过
    skip_reason: str = ""


@dataclass
class MappingResult:
    base_octave: int = 4
    notes: list[MappedNote] = field(default_factory=list)

    @property
    def in_range_count(self) -> int:
        return sum(1 for n in self.notes if n.in_range)

    @property
    def skip_count(self) -> int:
        return sum(1 for n in self.notes if not n.in_range)


# do..ti 对应键位
KEYS = ["Z", "X", "C", "V", "B", "N", "M"]
# 高高音 do 用的键
TOP_KEY = ","

_SHARP_PC = {1, 3, 6, 8, 10}
_DIATONIC = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}


def _reachable(pitch: int, base_oct: int) -> bool:
    """pitch 在基准=base_oct 下是否可演奏。"""
    d = pitch // 12 - 1 - base_oct
    if -1 <= d <= 1:
        return True
    if d == 2:
        pc = _mod(pitch, 12)
        return pc in (0, 1)   # 高高音 do / #do
    return False


def key_of_pitch(pitch: int) -> str:
    """任意音高 → z..m 键：先归到最近自然音再取键。"""
    pc = _mod(pitch, 12)
    idx = _DIATONIC.get(pc)
    if idx is None:
        pc = _mod(pc - 1, 12)     # 升号音降半音后取自然音
        idx = _DIATONIC[pc]
    return KEYS[idx]


def is_sharp_pitch(pitch: int) -> bool:
    return _mod(pitch, 12) in _SHARP_PC


def auto_base_octave(pitches: list[int]) -> int:
    """自动选基准八度，使可演奏区容纳最多音符（并列时靠近平均音区）。"""
    if not pitches:
        return 4
    octs = [p // 12 - 1 for p in pitches]
    min_o, max_o = min(octs), max(octs)
    mean_o = sum(octs) / len(octs)
    best_b, best_play = min_o, -1
    for b in range(min_o, max_o + 1):
        play = sum(1 for p in pitches if _reachable(p, b))
        if play > best_play or (play == best_play and abs(b - mean_o) < abs(best_b - mean_o)):
            best_play, best_b = play, b
    return best_b


def chord_root_only(notes: list[RawNote], eps: float = 0.025) -> list[RawNote]:
    """单音化：同一瞬间（±eps 秒）多个音一起响时，只保留最高音。

    流行编曲主旋律通常在最高声部，取最高最贴近原曲走向。
    """
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    keep: list[RawNote] = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1].start - ordered[i].start <= eps:
            j += 1
        keep.append(ordered[j])      # group 按音高升序，末位=最高
        i = j + 1
    return keep


def extract_skyline(notes: list[RawNote], eps: float = 0.03,
                    phrase_gap: float = 0.5) -> list[RawNote]:
    """天际线旋律提取：追踪旋律线条的连续性，适合多声部/和弦 MIDI。

    与 ``chord_root_only`` 不同，遇到同时发响的多个音时，不只取最高音，
    而是选离当前「天际线」最近的音，让旋律线条更连贯自然。

    算法：
    1. 按时序分组（eps 内算同时）
    2. 维护一条指数平滑的天际线 pitch
    3. 每组选最接近天际线的音（微弱偏好高音）
    4. 乐句间隙 (>phrase_gap) 重置天际线，允许旋律自然换音区

    这对以下场景特别有效：
    - 钢琴右手旋律+和弦填充（天际线会自动忽略填充音）
    - 八度重复（自然收敛到某个八度）
    - 弦乐四重奏等多声部编曲
    """
    if not notes:
        return []

    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))

    # 按起始时间分组
    groups: list[list[RawNote]] = []
    i = 0
    while i < len(ordered):
        group = [ordered[i]]
        j = i + 1
        while j < len(ordered) and ordered[j].start - ordered[i].start <= eps:
            group.append(ordered[j])
            j += 1
        groups.append(group)
        i = j

    skyline: Optional[float] = None
    melody: list[RawNote] = []

    for group in groups:
        if len(group) == 1:
            chosen = group[0]
        else:
            # 多音同时发响 → 选最接近天际线的
            if skyline is None:
                # 开头或刚重置 → 取最高音作为初始天际线
                chosen = group[-1]
            else:
                best_note: Optional[RawNote] = None
                best_score = float("-inf")
                for n in group:
                    dist = abs(n.pitch - skyline)
                    # 微弱偏好高音（系数 0.25），避免被低音和弦拉走
                    height_bias = n.pitch / 127.0 * 3.0
                    score = -dist + height_bias
                    if score > best_score:
                        best_score = score
                        best_note = n
                chosen = best_note if best_note is not None else group[-1]

        # 检查乐句间隙：长时间静默后重置天际线
        if melody:
            gap = chosen.start - melody[-1].end
            if gap > phrase_gap:
                skyline = None  # 下一组重新取最高
                # 当前这个音作为新乐句开头，重新初始化天际线
                skyline = float(chosen.pitch)

        # 指数平滑更新天际线
        if skyline is None:
            skyline = float(chosen.pitch)
        else:
            # 0.7 保留旧值 + 0.3 新值：平滑跟踪，不被偶然的装饰音带偏
            skyline = 0.7 * skyline + 0.3 * float(chosen.pitch)

        melody.append(chosen)

    return melody


def trim_leading_silence(notes: list[RawNote]) -> list[RawNote]:
    """去除开头整段空拍：整体平移到第一个音符从 0 秒开始。"""
    if not notes:
        return []
    first = min(n.start for n in notes)
    if first <= 0.001:
        return list(notes)
    return [RawNote(n.pitch, max(0.0, n.start - first), max(0.0, n.end - first), n.velocity)
            for n in notes]


def suggest_transpose_into_range(pitches: list[int]) -> int:
    """一键移调：返回把旋律整体移入演奏音域的最佳半音数。

    以基准八度可演奏区为目标，枚举 -24..+24，选可演奏音最多者（并列取绝对值最小）。
    """
    if not pitches:
        return 0
    best_t, best_play = 0, -1
    for t in range(-24, 25):
        moved = [p + t for p in pitches if 0 <= p + t <= 127]
        if not moved:
            continue
        b = auto_base_octave(moved)
        play = sum(1 for p in moved if _reachable(p, b))
        if play > best_play or (play == best_play and abs(t) < abs(best_t)):
            best_play, best_t = play, t
    return best_t


def map_notes(notes: list[RawNote], transpose: int = 0,
              manual_base_octave: Optional[int] = None) -> MappingResult:
    """把主旋律音符映射到乐器按键方案。"""
    result = MappingResult()

    valid = [n.pitch + transpose for n in notes if 0 <= n.pitch + transpose <= 127]
    base_octave = manual_base_octave if manual_base_octave is not None else auto_base_octave(valid)
    result.base_octave = base_octave

    for n in notes:
        p = n.pitch + transpose
        if p < 0 or p > 127:
            result.notes.append(MappedNote(p, n.start, n.end, " ", False, Slot.MID,
                                           False, "移调后超出 MIDI 音域"))
            continue

        oct_ = p // 12 - 1
        diff = oct_ - base_octave

        if diff < -1 or diff > 2:
            result.notes.append(MappedNote(p, n.start, n.end, key_of_pitch(p), is_sharp_pitch(p),
                                           Slot.MID, False, f"音区超出演奏范围(第{oct_}八度)"))
            continue

        if diff == 2:
            pc = _mod(p, 12)
            if pc not in (0, 1):
                result.notes.append(MappedNote(p, n.start, n.end, TOP_KEY, pc == 1,
                                               Slot.HIGH, False, "最高只能到 高高音#do"))
                continue
            result.notes.append(MappedNote(p, n.start, n.end, TOP_KEY, pc == 1,
                                           Slot.HIGH, True))
            continue

        result.notes.append(MappedNote(p, n.start, n.end, key_of_pitch(p), is_sharp_pitch(p),
                                        Slot(diff), True))
    return result


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(pitch: int) -> str:
    return f"{_NOTE_NAMES[_mod(pitch, 12)]}{pitch // 12 - 1}"


def describe(n: MappedNote) -> str:
    slot = {Slot.LOW: "低八度(左键)", Slot.HIGH: "高八度(右键)"}.get(n.slot, "基准八度")
    key_show = "，" if n.key == TOP_KEY else n.key
    sharp = "+升半音(中键) " if n.sharp else ""
    return f"{note_name(n.pitch)} → [{key_show}] {sharp}{slot}"
