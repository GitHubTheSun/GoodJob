"""把窗口吸到屏幕边缘，并算出贴边后的位置。"""

from __future__ import annotations

from dataclasses import dataclass

SNAP_PX = 22
PEEK = 18
HIDE_DELAY = 0.45


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int


def snap_edge(x: int, y: int, width: int, height: int, screen: Box, threshold: int = SNAP_PX) -> str | None:
    gaps = (
        ("left", abs(x - screen.left)),
        ("right", abs(screen.right - (x + width - 1))),
        ("top", abs(y - screen.top)),
    )
    best_name = None
    best_gap = threshold + 1
    for name, gap in gaps:
        if gap < best_gap:
            best_name = name
            best_gap = gap
    return best_name


def placed(
    edge: str | None,
    x: int,
    y: int,
    width: int,
    height: int,
    screen: Box,
    opened: bool,
    peek: int = PEEK,
) -> tuple[int, int]:
    if edge == "left":
        nx = screen.left if opened else screen.left - width + peek
        ny = _clamp(y, screen.top, screen.bottom - height + 1)
        return nx, ny
    if edge == "right":
        nx = (screen.right - width + 1) if opened else (screen.right - peek + 1)
        ny = _clamp(y, screen.top, screen.bottom - height + 1)
        return nx, ny
    if edge == "top":
        ny = screen.top if opened else screen.top - height + peek
        nx = _clamp(x, screen.left, screen.right - width + 1)
        return nx, ny
    return (
        _clamp(x, screen.left, screen.right - width + 1),
        _clamp(y, screen.top, screen.bottom - height + 1),
    )


def want_open(
    pinned: bool,
    held: bool,
    grace: bool,
    suppressed: bool,
    inside: bool,
    opened: bool,
    outside_for: float | None,
    docked: bool,
    delay: float = HIDE_DELAY,
) -> bool:
    if not docked:
        return True
    if suppressed:
        return False
    if pinned or held or grace:
        return True
    if inside:
        return True
    if not opened:
        return False
    if outside_for is None:
        return True
    return outside_for < delay


def _clamp(value: int, low: int, high: int) -> int:
    if high < low:
        return low
    return min(max(int(value), low), high)


def _self_check() -> None:
    screen = Box(0, 0, 1919, 1079)
    assert snap_edge(400, 200, 360, 640, screen) is None
    assert snap_edge(10, 200, 360, 640, screen) == "left"
    assert snap_edge(1919 - 360 + 1, 200, 360, 640, screen) == "right"
    assert snap_edge(400, 4, 360, 640, screen) == "top"
    assert placed("right", 0, 200, 360, 640, screen, True, 18) == (1919 - 360 + 1, 200)
    assert placed("right", 0, 200, 360, 640, screen, False, 18) == (1919 - 18 + 1, 200)
    assert placed("left", 0, 200, 360, 640, screen, False, 18) == (0 - 360 + 18, 200)
    assert placed("top", 100, 0, 360, 640, screen, False, 18) == (100, 0 - 640 + 18)
    assert want_open(False, False, False, False, False, True, 1, False) is True
    assert want_open(False, False, False, False, True, False, None, True) is True
    assert want_open(False, False, False, True, True, True, None, True) is False
    assert want_open(False, False, False, False, False, True, 0.2, True) is True
    assert want_open(False, False, False, False, False, True, 0.6, True) is False
    print("snap checks passed")


if __name__ == "__main__":
    _self_check()
