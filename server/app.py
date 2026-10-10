"""FastAPI backend: every browser tab gets its own session (audio source + analyzer). The
session runs the DSP every hop and streams the results to its tab over a WebSocket.

Audio comes from one of three places:
  - the visitor's browser microphone, streamed over the same WebSocket (works when deployed),
  - a microphone on the machine running the server (sounddevice; local runs only),
  - a WAV file, uploaded or picked from recordings/, played in real time."""
import asyncio
import json
import re
import secrets
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket
from fastapi.staticfiles import StaticFiles

from dsp import Analyzer, Config
from .sources import BrowserMicSource, FileSource, MicSource, list_input_devices, read_wav, write_wav

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
REC_DIR = ROOT / "recordings"
REC_DIR.mkdir(exist_ok=True)
MAX_UPLOAD = 50 * 1024 * 1024


class Session:
    def __init__(self, ws: WebSocket):
        self.sid = secrets.token_urlsafe(12)
        self.ws = ws
        self.mic: MicSource | BrowserMicSource | None = None    # the live input
        self.mic_device = None
        self.mic_error: str | None = None
        self.file: FileSource | None = None
        self.a4 = 440.0
        self.gate_db = Config.gate_db_above_noise
        self.analyzer: Analyzer | None = None
        self.events: list[dict] = []

    # ---------- sources ----------
    @property
    def source(self):
        return self.file or self.mic

    def open_mic(self, device=None):
        self.close_mic()
        try:
            self.mic = MicSource(device)
            self.mic_device, self.mic_error = device, None
        except Exception as e:                     # no mic / no PortAudio (e.g. in the cloud)
            self.mic_error = f"{type(e).__name__}: {e}"
        self._new_analyzer()

    def open_browser_mic(self, fs, name):
        self.close_mic()
        self.mic = BrowserMicSource(int(np.clip(fs, 8000, 192000)), str(name or ""))
        self.mic_device, self.mic_error = None, None
        self._new_analyzer()

    def close_mic(self):
        if self.mic:
            self.mic.close()
            self.mic = None

    def feed(self, data: bytes):
        if isinstance(self.mic, BrowserMicSource):
            self.mic.feed(data)

    def play_file(self, x, fs, name):
        self.file = FileSource(x, fs, name)
        self._new_analyzer()

    def stop_file(self):
        if self.file:
            self.file = None
            self._new_analyzer()
            self.events.append({"type": "file_ended"})

    def _new_analyzer(self):
        src = self.source
        if src is None:
            self.analyzer = None
            return
        cfg = Config(fs=src.fs, a4=self.a4, gate_db_above_noise=self.gate_db)
        self.analyzer = Analyzer(cfg)
        if src.kind == "file":
            # files start with the music, not with room noise: skip calibration, use a
            # fixed low noise floor instead
            self.analyzer.tracker._calib_frames = 0
            self.analyzer.tracker.noise_db = -70.0

    def status(self) -> dict:
        src = self.source
        return {
            "type": "status",
            "sid": self.sid,
            "source": None if src is None else {
                "kind": src.kind, "name": src.name, "fs": src.fs,
                "duration": getattr(src, "duration", None),
            },
            "live": None if self.mic is None else self.mic.kind,
            "mic_error": self.mic_error,
            "mic_device": self.mic_device,
            "a4": self.a4,
            "gate_db": self.gate_db,
            "freqs": None if self.analyzer is None else
                     [round(f, 2) for f in self.analyzer.display_freqs.tolist()],
            "hop_sec": Config.hop_sec,
        }

    # ---------- main loop ----------
    async def run(self):
        hop = Config.hop_sec
        next_t = time.monotonic()
        while True:
            next_t += hop
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))
            if time.monotonic() - next_t > 1.0:      # fell far behind (laptop slept): resync
                next_t = time.monotonic()

            if self.file and self.file.finished:
                self.stop_file()
                await self.send(self.status())
            for ev in self.events:
                await self.send(ev)
            self.events.clear()

            src, an = self.source, self.analyzer
            if src is None or an is None:
                continue
            x = src.window(an.cfg.n_win)
            res = await asyncio.to_thread(an.process, x)
            res["type"] = "frame"
            if src.kind == "file":
                res["file_pos"] = round(src.position() / src.fs, 2)
            await self.send(res)

    async def send(self, msg: dict):
        try:
            await self.ws.send_text(json.dumps(msg, separators=(",", ":")))
        except Exception:
            pass                                     # closing: the receive loop ends the session

    # ---------- control from the UI ----------
    async def handle(self, msg: dict):
        cmd = msg.get("cmd")
        if cmd == "calibrate" and self.analyzer:
            self.analyzer.calibrate()
        elif cmd == "a4":
            self.a4 = float(np.clip(float(msg["value"]), 400, 480))
            if self.analyzer:
                self.analyzer.set_a4(self.a4)
        elif cmd == "gate":
            self.gate_db = float(np.clip(float(msg["value"]), 3, 40))
            if self.analyzer:
                self.analyzer.cfg.gate_db_above_noise = self.gate_db
        elif cmd == "device":                        # a microphone on the server machine
            dev = msg.get("value")
            self.open_mic(None if dev in (None, "", "default") else int(dev))
        elif cmd == "browser_mic":                   # PCM chunks follow as binary messages
            self.open_browser_mic(float(msg.get("fs", 48000)), msg.get("name"))
        elif cmd == "browser_mic_stop":
            if isinstance(self.mic, BrowserMicSource):
                self.close_mic()
                self._new_analyzer()
        elif cmd == "stop_file":
            self.stop_file()
        await self.send(self.status())


sessions: dict[str, Session] = {}
app = FastAPI(title="Guitar FFT note & chord detector")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    s = Session(ws)
    sessions[s.sid] = s
    s.open_mic(getattr(app.state, "device", None))
    task = asyncio.create_task(s.run())
    try:
        await s.send(s.status())
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("bytes") is not None:
                s.feed(m["bytes"])
            elif m.get("text"):
                try:
                    msg = json.loads(m["text"])
                except json.JSONDecodeError:
                    continue
                await s.handle(msg)
    finally:
        task.cancel()
        sessions.pop(s.sid, None)
        s.close_mic()


def _session(sid: str) -> Session:
    s = sessions.get(sid)
    if s is None:
        raise HTTPException(409, "not connected: reload the page")
    return s


@app.get("/api/devices")
def devices():
    try:
        return {"devices": list_input_devices()}
    except Exception as e:
        return {"devices": [], "error": str(e)}


def _load_and_play(s: Session, data: bytes, name: str):
    try:
        x, fs = read_wav(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if len(x) < fs * 0.5:
        raise HTTPException(400, "file is shorter than 0.5 s")
    peak = np.abs(x).max()
    if peak > 0:
        x = x * (0.5 / peak)     # normalise so quiet recordings still open the gate
    s.play_file(x, fs, name)
    s.events.append(s.status())
    return {"name": name, "fs": fs, "duration": round(len(x) / fs, 2)}


@app.post("/api/upload")
async def upload(sid: str, file: UploadFile = File(...)):
    s = _session(sid)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file is larger than 50 MB")
    return _load_and_play(s, data, file.filename or "upload.wav")


@app.get("/api/recordings")
def recordings():
    files = sorted(REC_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"recordings": [{"name": p.name, "size": p.stat().st_size} for p in files]}


@app.post("/api/play/{name}")
def play_recording(name: str, sid: str):
    s = _session(sid)
    path = (REC_DIR / name).resolve()
    if path.parent != REC_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "no such recording")
    return _load_and_play(s, path.read_bytes(), name)


@app.post("/api/record")
def record(sid: str, sec: float = 5.0, label: str = ""):
    s = _session(sid)
    if s.mic is None:
        raise HTTPException(409, "no microphone is on")
    sec = float(np.clip(sec, 1, 15))
    x = s.mic.recent(sec)
    safe = re.sub(r"[^A-Za-z0-9#_-]+", "_", label).strip("_")
    name = time.strftime("rec-%Y%m%d-%H%M%S") + (f"-{safe}" if safe else "") + ".wav"
    write_wav(REC_DIR / name, x, s.mic.fs)
    return {"name": name, "duration": sec}


app.mount("/recordings", StaticFiles(directory=REC_DIR), name="recordings")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
