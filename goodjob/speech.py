"""联网语音识别。录音用本机麦克风，识别走网络，不用 Windows 语音引擎。"""

from __future__ import annotations

import ctypes
import os
import socket
import struct
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from goodjob.qt_compat import QObject, Signal


def _bin_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "goodjob" / "bin"
    return Path(__file__).resolve().parent / "bin"


_BIN = _bin_dir()
_WHDR_DONE = 0x00000001
_WHDR_PREPARED = 0x00000002


class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class _WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_void_p),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
    ]


@dataclass
class SpeechOutcome:
    ok: bool
    text: str = ""
    error: str = ""


class ListenWorker(QObject):
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, language: str, api_key: str = "") -> None:
        if self.running():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(language, self._stop, api_key),
            name="goodjob-speech",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, language: str, stop: threading.Event, api_key: str) -> None:
        try:
            outcome = listen(language, stop, api_key)
        except Exception:
            outcome = SpeechOutcome(False, error="failed")
        self.finished.emit(outcome)


def listen(language: str, stop: threading.Event | None = None, api_key: str = "") -> SpeechOutcome:
    stop = stop or threading.Event()
    api_key = (api_key or "").strip()
    if api_key:
        if not host_ok("api.groq.com"):
            return SpeechOutcome(False, error="offline")
    elif not host_ok("www.google.com"):
        return SpeechOutcome(False, error="need_key")
    try:
        pcm, heard = record_pcm(stop)
    except OSError:
        return SpeechOutcome(False, error="no_mic")
    if not heard or not pcm:
        return SpeechOutcome(False, error="empty")
    try:
        text = _groq_transcribe(pcm, language, api_key) if api_key else transcribe(pcm, language)
    except _Quiet:
        return SpeechOutcome(False, error="empty")
    except _Unreachable:
        return SpeechOutcome(False, error="network")
    except Exception:
        return SpeechOutcome(False, error="failed")
    text = (text or "").strip()
    if not text:
        return SpeechOutcome(False, error="empty")
    return SpeechOutcome(True, text=text)


def host_ok(host: str) -> bool:
    try:
        with socket.create_connection((host, 443), 2):
            return True
    except OSError:
        return False


def network_ok() -> bool:
    return host_ok("www.google.com") or host_ok("api.groq.com")


def _groq_transcribe(pcm: bytes, language: str, api_key: str) -> str:
    import json
    import urllib.error
    import urllib.request

    wav = _wav_bytes(pcm)
    boundary = "----GoodJobBoundary7f3a"
    lang = "zh" if language.lower().startswith("zh") else "en"
    chunks = [
        _field(boundary, "model", "whisper-large-v3-turbo"),
        _field(boundary, "language", lang),
        _field(boundary, "response_format", "json"),
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8"),
        wav,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        data=b"".join(chunks),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _Unreachable() from exc
    except urllib.error.URLError as exc:
        raise _Unreachable() from exc
    return str(payload.get("text") or "")


def _field(boundary: str, name: str, value: str) -> bytes:
    return (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
    ).encode("utf-8")


def _wav_bytes(pcm: bytes, rate: int = 16000) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def transcribe(pcm: bytes, language: str) -> str:
    _ensure_flac()
    import speech_recognition as sr

    audio = sr.AudioData(pcm, 16000, 2)
    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 20
    try:
        return recognizer.recognize_google(audio, language=language)
    except sr.UnknownValueError as exc:
        raise _Quiet() from exc
    except sr.RequestError as exc:
        raise _Unreachable() from exc


def record_pcm(stop: threading.Event, seconds: float = 12, rate: int = 16000) -> tuple[bytes, bool]:
    winmm = ctypes.WinDLL("winmm")
    _bind(winmm)
    if int(winmm.waveInGetNumDevs()) <= 0:
        raise OSError("no microphone")

    fmt = _WAVEFORMATEX()
    fmt.wFormatTag = 1
    fmt.nChannels = 1
    fmt.nSamplesPerSec = rate
    fmt.wBitsPerSample = 16
    fmt.nBlockAlign = 2
    fmt.nAvgBytesPerSec = rate * 2
    fmt.cbSize = 0

    handle = ctypes.c_void_p()
    opened = winmm.waveInOpen(ctypes.byref(handle), 0xFFFFFFFF, ctypes.byref(fmt), None, None, 0)
    if opened != 0:
        raise OSError(f"microphone {opened}")

    chunk = rate * 2 // 5
    headers: list[_WAVEHDR] = []
    buffers: list[ctypes.Array] = []
    pieces: list[bytes] = []
    heard = False
    quiet_chunks = 0
    started = time.monotonic()
    try:
        for _ in range(6):
            buf = ctypes.create_string_buffer(chunk)
            hdr = _WAVEHDR()
            hdr.lpData = ctypes.addressof(buf)
            hdr.dwBufferLength = chunk
            if winmm.waveInPrepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(hdr)) != 0:
                raise OSError("prepare")
            if winmm.waveInAddBuffer(handle, ctypes.byref(hdr), ctypes.sizeof(hdr)) != 0:
                raise OSError("buffer")
            headers.append(hdr)
            buffers.append(buf)
        if winmm.waveInStart(handle) != 0:
            raise OSError("start")
        while time.monotonic() - started < seconds:
            if stop.is_set() and pieces:
                break
            time.sleep(0.05)
            for hdr, buf in zip(headers, buffers):
                if not (hdr.dwFlags & _WHDR_DONE):
                    continue
                size = int(hdr.dwBytesRecorded)
                if size:
                    data = bytes(buf.raw[:size])
                    pieces.append(data)
                    if _rms(data) >= 700:
                        heard = True
                        quiet_chunks = 0
                    elif heard:
                        quiet_chunks += 1
                hdr.dwBytesRecorded = 0
                hdr.dwFlags = _WHDR_PREPARED
                winmm.waveInAddBuffer(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
            if heard and quiet_chunks >= 6:
                break
            if not heard and time.monotonic() - started > 8:
                break
    finally:
        winmm.waveInStop(handle)
        winmm.waveInReset(handle)
        for hdr in headers:
            winmm.waveInUnprepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.waveInClose(handle)
    return b"".join(pieces), heard


class _Quiet(Exception):
    pass


class _Unreachable(Exception):
    pass


def _bind(winmm: ctypes.WinDLL) -> None:
    winmm.waveInGetNumDevs.restype = wintypes.UINT
    winmm.waveInOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.UINT,
        ctypes.POINTER(_WAVEFORMATEX),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    winmm.waveInOpen.restype = wintypes.UINT
    for name in ("waveInPrepareHeader", "waveInUnprepareHeader", "waveInAddBuffer"):
        fn = getattr(winmm, name)
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), wintypes.UINT]
        fn.restype = wintypes.UINT
    for name in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
        fn = getattr(winmm, name)
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = wintypes.UINT


def _rms(data: bytes) -> float:
    count = len(data) // 2
    if count <= 0:
        return 0
    samples = struct.unpack("<" + "h" * count, data[: count * 2])
    total = sum(sample * sample for sample in samples)
    return (total / count) ** 0.5


def _ensure_flac() -> None:
    folder = str(_BIN)
    current = os.environ.get("PATH", "")
    if folder.lower() not in current.lower():
        os.environ["PATH"] = folder + os.pathsep + current
