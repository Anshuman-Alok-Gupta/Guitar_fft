"""Audio inputs: live microphone (ring buffer) and WAV file played back in real time."""
import struct
import threading
import time
import wave
from pathlib import Path

import numpy as np


class RingBuffer:
    """Fixed-size circular buffer: the audio callback writes in place (no allocation,
    unlike np.roll in the original cie2.py), readers copy out the latest n samples."""

    def __init__(self, size: int):
        self.buf = np.zeros(size, dtype=np.float32)
        self.pos = 0                 # next write index
        self.lock = threading.Lock()

    def write(self, x: np.ndarray):
        n, size = len(x), len(self.buf)
        if n >= size:
            x, n = x[-size:], size
        with self.lock:
            end = self.pos + n
            if end <= size:
                self.buf[self.pos:end] = x
            else:
                k = size - self.pos
                self.buf[self.pos:] = x[:k]
                self.buf[:n - k] = x[k:]
            self.pos = end % size

    def latest(self, n: int) -> np.ndarray:
        with self.lock:
            idx = (self.pos - n + np.arange(n)) % len(self.buf)
            return self.buf[idx].copy()


def list_input_devices():
    import sounddevice as sd
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append({
                "id": i,
                "name": d["name"],
                "api": apis[d["hostapi"]]["name"],
                "samplerate": int(d["default_samplerate"]),
                "default": i == default_in,
            })
    return out


class MicSource:
    kind = "mic"

    def __init__(self, device=None, buffer_sec: float = 15.0):
        import sounddevice as sd
        info = sd.query_devices(device, kind="input")
        self.name = info["name"]
        self.fs = int(info["default_samplerate"])      # the mic's native rate
        self.ring = RingBuffer(int(buffer_sec * self.fs))
        self.status_errors = 0
        self.stream = sd.InputStream(device=device, samplerate=self.fs, channels=1,
                                     dtype="float32", blocksize=1024, callback=self._callback)
        self.stream.start()

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.status_errors += 1
        self.ring.write(indata[:, 0])                  # first channel only (mono)

    def window(self, n: int) -> np.ndarray:
        return self.ring.latest(n)

    def recent(self, sec: float) -> np.ndarray:
        return self.ring.latest(min(int(sec * self.fs), len(self.ring.buf)))

    @property
    def finished(self):
        return False

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


def read_wav(data: bytes):
    """Minimal RIFF/WAVE reader: PCM 8/16/24/32-bit and IEEE float 32/64, any channel
    count (downmixed to mono). Returns (float64 samples in -1..1, sample rate)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, ch, fs, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:          # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, fs, bits)
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError("WAV file has no fmt/data chunk")
    tag, ch, fs, bits = fmt
    width = bits // 8
    raw = raw[:len(raw) // (width * ch) * width * ch]
    if tag == 3:
        x = np.frombuffer(raw, dtype="<f4" if bits == 32 else "<f8").astype(float)
    elif tag == 1:
        if bits == 8:
            x = (np.frombuffer(raw, np.uint8).astype(float) - 128) / 128
        elif bits == 16:
            x = np.frombuffer(raw, "<i2") / 32768.0
        elif bits == 24:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            x = np.where(v >= 1 << 23, v - (1 << 24), v) / float(1 << 23)
        elif bits == 32:
            x = np.frombuffer(raw, "<i4") / 2147483648.0
        else:
            raise ValueError(f"unsupported PCM bit depth {bits}")
    else:
        raise ValueError(f"unsupported WAV encoding (format tag {tag}); export as PCM WAV")
    x = x.reshape(-1, ch).mean(axis=1)
    return x, fs


def write_wav(path: Path, x: np.ndarray, fs: int):
    x = np.clip(np.asarray(x, dtype=float), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes((x * 32767).astype("<i2").tobytes())


class FileSource:
    """Plays a decoded WAV through the analyzer in real time, as if it were the mic."""
    kind = "file"

    def __init__(self, x: np.ndarray, fs: int, name: str):
        self.x = np.asarray(x, dtype=np.float32)
        self.fs = fs
        self.name = name
        self.duration = len(x) / fs
        self.t0 = time.monotonic()

    def position(self) -> int:
        return int((time.monotonic() - self.t0) * self.fs)

    def window(self, n: int) -> np.ndarray:
        end = self.position()
        out = np.zeros(n, dtype=np.float32)
        lo, hi = max(end - n, 0), min(end, len(self.x))
        if hi > lo:
            out[n - (end - lo):n - (end - hi)] = self.x[lo:hi]
        return out

    @property
    def finished(self):
        return self.position() > len(self.x) + self.fs // 2

    def close(self):
        pass
