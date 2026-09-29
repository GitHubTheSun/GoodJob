"""从一句话里拆出多条记事，并认出时间。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_CN = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_DEFAULT_HOUR = {
    "早上": 9,
    "上午": 9,
    "中午": 12,
    "下午": 15,
    "晚上": 20,
    "傍晚": 18,
}

_NUM = r"(?P<num>\d+|[一二两三四五六七八九十])"
_PERIOD = r"(?P<period>早上|上午|中午|下午|晚上|傍晚)"
_HOUR = r"(?P<hour>\d{1,2}|[一二两三四五六七八九十])"
_HALF = r"(?P<half>半)?"
_CLOCK = r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?"


def parse_task_text(text: str, now: datetime | None = None) -> tuple[str, datetime | None]:
    now = now or datetime.now()
    raw = text.strip()
    if not raw:
        return "", None

    found: list[tuple[int, int, datetime]] = []
    for pattern, builder in _patterns(now):
        match = pattern.search(raw)
        if not match:
            continue
        when = builder(match)
        if when is None:
            continue
        found.append((match.start(), match.end(), when))

    if not found:
        return _clean(raw), None

    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    start, end, when = found[0]
    title = _clean(raw[:start] + raw[end:])
    if title:
        return title, when
    return ("Note" if re.search(r"[A-Za-z]", raw) else "记事"), when


def extract_items(text: str, now: datetime | None = None) -> list[tuple[str, datetime | None]]:
    """把一段话拆成若干条 (标题, 时间)。"""
    now = now or datetime.now()
    items: list[tuple[str, datetime | None]] = []
    for chunk in _split(text):
        title, when = parse_task_text(chunk, now)
        title = title.strip()
        if title:
            items.append((title, when))
    return items


def format_when(when: datetime, now: datetime | None = None, lang: str = "zh") -> str:
    now = now or datetime.now()
    delta = (when.date() - now.date()).days
    clock = f"{when:%H:%M}"
    if lang == "en":
        if delta == 0:
            return f"Today {clock}"
        if delta == 1:
            return f"Tomorrow {clock}"
        if delta == 2:
            return f"Day after {clock}"
        return f"{when:%m-%d} {clock}"
    if delta == 0:
        return f"今天 {clock}"
    if delta == 1:
        return f"明天 {clock}"
    if delta == 2:
        return f"后天 {clock}"
    return f"{when.month}/{when.day} {clock}"


def _patterns(now: datetime) -> list[tuple[re.Pattern[str], callable]]:
    patterns: list[tuple[re.Pattern[str], callable]] = [
        (re.compile(r"半个?\s*小时后"), lambda m: now + timedelta(minutes=30)),
        (re.compile(r"\bin\s+half\s+an\s+hour\b", re.I), lambda m: now + timedelta(minutes=30)),
        (re.compile(_NUM + r"\s*个?\s*小时后"), lambda m: _after_number(m, now, hours=True)),
        (re.compile(_NUM + r"\s*分钟后"), lambda m: _after_number(m, now, hours=False)),
        (re.compile(r"\bin\s+(?P<num>\d+)\s+hours?\b", re.I), lambda m: _after_number(m, now, hours=True)),
        (re.compile(r"\bin\s+(?P<num>\d+)\s+minutes?\b", re.I), lambda m: _after_number(m, now, hours=False)),
        (re.compile(r"今晚\s*" + _HOUR + r"?\s*点?" + _HALF), lambda m: _tonight(m, now)),
        (
            re.compile(r"\btonight(?:\s+at)?\s+" + _CLOCK, re.I),
            lambda m: _english_clock(m, now, 0, evening=True),
        ),
    ]
    for word, offset in (("今天", 0), ("明天", 1), ("后天", 2)):
        patterns.append(
            (
                re.compile(word + r"\s*" + _PERIOD + r"\s*" + _HOUR + r"?\s*点?" + _HALF),
                lambda m, offset=offset: _clock(m, now, offset, True),
            )
        )
        patterns.append(
            (
                re.compile(word + r"\s*" + _HOUR + r"\s*点" + _HALF),
                lambda m, offset=offset: _clock(m, now, offset, False),
            )
        )
    patterns.extend(
        [
            (re.compile(_PERIOD + r"\s*" + _HOUR + r"\s*点" + _HALF), lambda m: _clock(m, now, 0, False)),
            (re.compile(r"(今天|明天|后天)(?!的)"), lambda m: _bare_day(m, now)),
            (
                re.compile(r"\b(?:the\s+)?day\s+after\s+tomorrow(?:\s+at\s+" + _CLOCK + r")?", re.I),
                lambda m: _english_day(m, now, 2),
            ),
            (re.compile(r"\btomorrow\s+morning\b", re.I), lambda m: _on_day(now, 1, 9, 0, False)),
            (re.compile(r"\btomorrow(?:\s+at)?\s+" + _CLOCK, re.I), lambda m: _english_clock(m, now, 1, evening=False)),
            (re.compile(r"\btoday(?:\s+at)?\s+" + _CLOCK, re.I), lambda m: _english_clock(m, now, 0, evening=False)),
            (re.compile(r"\btomorrow\b(?!'s)", re.I), lambda m: _on_day(now, 1, 9, 0, False)),
            (re.compile(r"\bat\s+" + _CLOCK, re.I), lambda m: _english_clock(m, now, 0, evening=False)),
        ]
    )
    return patterns


def _split(text: str) -> list[str]:
    cooked = text.strip()
    cooked = re.sub(r"\s+(?:and then|then|also)\s+", "\n", cooked, flags=re.I)
    cooked = re.sub(r"\s+and\s+", "\n", cooked, flags=re.I)
    cooked = re.sub(r"然后|另外|还有|并且|以及|还要", "\n", cooked)
    parts = re.split(r"[。；;！!？?\n，,、]+", cooked)
    return [part.strip() for part in parts if part.strip()]


def _after_number(match: re.Match[str], now: datetime, hours: bool) -> datetime | None:
    amount = _number(match.group("num"))
    if amount is None or amount <= 0:
        return None
    if hours:
        return now + timedelta(hours=amount)
    return now + timedelta(minutes=amount)


def _tonight(match: re.Match[str], now: datetime) -> datetime | None:
    hour_token = match.group("hour")
    hour = 20 if not hour_token else _number(hour_token)
    if hour is None:
        return None
    if hour < 12:
        hour += 12
    minute = 30 if match.group("half") else 0
    return _on_day(now, 0, hour, minute, roll_if_past=True)


def _clock(match: re.Match[str], now: datetime, day_offset: int, allow_missing_hour: bool) -> datetime | None:
    groups = match.groupdict()
    period = groups.get("period")
    hour_token = groups.get("hour")
    half = bool(groups.get("half"))
    if hour_token:
        hour = _number(hour_token)
        if hour is None:
            return None
        hour = _apply_period(hour, period)
    elif allow_missing_hour and period:
        hour = _DEFAULT_HOUR[period]
    else:
        return None
    minute = 30 if half else 0
    return _on_day(now, day_offset, hour, minute, roll_if_past=day_offset == 0)


def _bare_day(match: re.Match[str], now: datetime) -> datetime | None:
    word = match.group(1)
    if word == "明天":
        return _on_day(now, 1, 9, 0, False)
    if word == "后天":
        return _on_day(now, 2, 9, 0, False)
    if now.hour < 9:
        return _on_day(now, 0, 9, 0, False)
    if now.hour < 18:
        return _on_day(now, 0, 18, 0, False)
    return _on_day(now, 1, 9, 0, False)


def _english_clock(match: re.Match[str], now: datetime, day_offset: int, evening: bool) -> datetime | None:
    groups = match.groupdict()
    hour_token = groups.get("hour")
    if not hour_token:
        return _on_day(now, day_offset, 20 if evening else 9, 0, roll_if_past=day_offset == 0)
    hour = _apply_ampm(int(hour_token), groups.get("ampm"), assume_evening=evening)
    minute = int(groups.get("minute") or 0)
    return _on_day(now, day_offset, hour, minute, roll_if_past=day_offset == 0)


def _english_day(match: re.Match[str], now: datetime, day_offset: int) -> datetime | None:
    if match.groupdict().get("hour"):
        return _english_clock(match, now, day_offset, evening=False)
    return _on_day(now, day_offset, 9, 0, False)


def _apply_ampm(hour: int, ampm: str | None, assume_evening: bool) -> int:
    if ampm:
        token = ampm.lower().replace(".", "")
        if token == "pm" and hour < 12:
            return hour + 12
        if token == "am" and hour == 12:
            return 0
        return hour
    if assume_evening and hour < 12:
        return hour + 12
    if hour < 8:
        return hour + 12
    return hour


def _apply_period(hour: int, period: str | None) -> int:
    if period in ("下午", "晚上", "傍晚") and hour < 12:
        return hour + 12
    if period == "中午" and hour < 11:
        return hour + 12
    if period in ("早上", "上午") and hour == 12:
        return 0
    return hour


def _on_day(now: datetime, day_offset: int, hour: int, minute: int, roll_if_past: bool) -> datetime | None:
    if hour > 23 or minute > 59 or hour < 0:
        return None
    day = now.date() + timedelta(days=day_offset)
    when = datetime(day.year, day.month, day.day, hour, minute)
    if roll_if_past and when <= now:
        when += timedelta(days=1)
    return when


def _number(token: str | None) -> int | None:
    if not token:
        return None
    if token.isdigit():
        return int(token)
    return _CN.get(token)


def _clean(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^[，,。.!！?？、\s]+|[，,。.!！?？、\s]+$", "", title)
    title = re.sub(r"^(请)?(记得)?提醒我(一下)?", "", title).strip()
    title = re.sub(r"^记得(一下)?", "", title).strip()
    title = re.sub(
        r"^(please\s+)?(remind me to|remember to)\s+",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"^(the|a|an)\s+", "", title, flags=re.I)
    title = re.sub(r"^[，,。.!！?？、\s]+|[，,。.!！?？、\s]+$", "", title)
    return title.strip()


def _self_check() -> None:
    now = datetime(2026, 9, 28, 10, 55)
    cases = [
        ("10分钟后喝水", "喝水", datetime(2026, 9, 28, 11, 5)),
        ("喝水", "喝水", None),
        ("提醒我半小时后站起来", "站起来", datetime(2026, 9, 28, 11, 25)),
        ("明天9点开会", "开会", datetime(2026, 9, 29, 9, 0)),
        ("明天的报告", "明天的报告", None),
        ("今晚8点跑步", "跑步", datetime(2026, 9, 28, 20, 0)),
        ("明天晚上8点开会", "开会", datetime(2026, 9, 29, 20, 0)),
        ("今天下午3点半面试", "面试", datetime(2026, 9, 28, 15, 30)),
        ("早上8点吃药", "吃药", datetime(2026, 9, 29, 8, 0)),
        ("两小时后回邮件", "回邮件", datetime(2026, 9, 28, 12, 55)),
        ("一个小时后喝水", "喝水", datetime(2026, 9, 28, 11, 55)),
        ("明天早上开会", "开会", datetime(2026, 9, 29, 9, 0)),
        ("准备今晚8点的材料", "准备的材料", datetime(2026, 9, 28, 20, 0)),
        ("后天早上交报告", "交报告", datetime(2026, 9, 30, 9, 0)),
        ("in 10 minutes drink water", "drink water", datetime(2026, 9, 28, 11, 5)),
        ("tomorrow at 3pm the meeting", "meeting", datetime(2026, 9, 29, 15, 0)),
    ]
    failed = 0
    for text, title, when in cases:
        got_title, got_when = parse_task_text(text, now)
        if got_title != title or got_when != when:
            failed += 1
            print(f"FAIL {text!r} -> {(got_title, got_when)} expected {(title, when)}")
    items = extract_items("明天开会，后天早上交报告，记得买牛奶", now)
    expected = [
        ("开会", datetime(2026, 9, 29, 9, 0)),
        ("交报告", datetime(2026, 9, 30, 9, 0)),
        ("买牛奶", None),
    ]
    if items != expected:
        failed += 1
        print(f"FAIL extract {items!r}")
    english = extract_items("in 10 minutes drink water, and tomorrow at 3pm the meeting", now)
    expected_en = [
        ("drink water", datetime(2026, 9, 28, 11, 5)),
        ("meeting", datetime(2026, 9, 29, 15, 0)),
    ]
    if english != expected_en:
        failed += 1
        print(f"FAIL english extract {english!r}")
    if failed:
        raise SystemExit(f"{failed} parser checks failed")
    print(f"{len(cases) + 2} parser checks passed")


if __name__ == "__main__":
    _self_check()
