"""FastAPI backend: runs the DSP on the active audio source every hop and streams the
results to the browser over a WebSocket."""
import asyncio
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from dsp import Analyzer, Config
from .sources import FileSource, MicSource, list_input_devices, read_wav, write_wav

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
REC_DIR = ROOT / "recordings"
REC_DIR.mkdir(exist_ok=True)


class Engine:
    def __init__(self):
        self.mic: MicSource | None = None
        self.mic_device = None
        self.mic_error: str | None = None
        self.file: FileSource | None = None
        self.a4 = 440.0
        self.gate_db = Config.gate_db_above_noise
        self.analyzer: Analyzer | None = None
        self.clients: set[WebSocket] = set()
        self.events: list[dict] = []

    # ---------- sources ----------
    @property
    def source(self):
        return self.file or self.mic

    def open_mic(self, device=None):
        if self.mic:
            self.mic.close()
            self.mic = None
        try:
            self.mic = MicSource(device)
            self.mic_device, self.mic_error = device, None
        except Exception as e:                     # no mic / device busy: keep running for files
            self.mic_error = f"{type(e).__name__}: {e}"
        self._new_analyzer()

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
            "source": None if src is None else {
                "kind": src.kind, "name": src.name, "fs": src.fs,
                "duration": getattr(src, "duration", None),
            },
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
                await self.broadcast(self.status())
            for ev in self.events:
                await self.broadcast(ev)
            self.events.clear()

            src, an = self.source, self.analyzer
            if src is None or an is None or not self.clients:
                continue
            x = src.window(an.cfg.n_win)
            res = await asyncio.to_thread(an.process, x)
            res["type"] = "frame"
            if src.kind == "file":
                res["file_pos"] = round(src.position() / src.fs, 2)
            await self.broadcast(res)

    async def broadcast(self, msg: dict):
        if not self.clients:
            return
        text = json.dumps(msg, separators=(",", ":"))
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

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
        elif cmd == "device":
            dev = msg.get("value")
            self.open_mic(None if dev in (None, "", "default") else int(dev))
        elif cmd == "stop_file":
            self.stop_file()
        await self.broadcast(self.status())


engine = Engine()


@asynccontextmanager
async def lifespan(app):
    engine.open_mic(getattr(app.state, "device", None))
    task = asyncio.create_task(engine.run())
    yield
    task.cancel()
    if engine.mic:
        engine.mic.close()


app = FastAPI(title="Guitar FFT note & chord detector", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    engine.clients.add(ws)
    await ws.send_text(json.dumps(engine.status()))
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                continue
            await engine.handle(msg)
    except WebSocketDisconnect:
        pass
    finally:
        engine.clients.discard(ws)


@app.get("/api/devices")
def devices():
    try:
        return {"devices": list_input_devices(), "current": engine.mic_device}
    except Exception as e:
        return {"devices": [], "current": None, "error": str(e)}


def _load_and_play(data: bytes, name: str):
    try:
        x, fs = read_wav(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if len(x) < fs * 0.5:
        raise HTTPException(400, "file is shorter than 0.5 s")
    peak = np.abs(x).max()
    if peak > 0:
        x = x * (0.5 / peak)     # normalise so quiet recordings still open the gate
    engine.play_file(x, fs, name)
    engine.events.append(engine.status())
    return {"name": name, "fs": fs, "duration": round(len(x) / fs, 2)}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    return _load_and_play(data, file.filename or "upload.wav")


@app.get("/api/recordings")
def recordings():
    files = sorted(REC_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"recordings": [{"name": p.name, "size": p.stat().st_size} for p in files]}


@app.post("/api/play/{name}")
def play_recording(name: str):
    path = (REC_DIR / name).resolve()
    if path.parent != REC_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "no such recording")
    return _load_and_play(path.read_bytes(), name)


@app.post("/api/record")
def record(sec: float = 5.0, label: str = ""):
    if engine.mic is None:
        raise HTTPException(409, engine.mic_error or "microphone is not available")
    sec = float(np.clip(sec, 1, 15))
    x = engine.mic.recent(sec)
    safe = re.sub(r"[^A-Za-z0-9#_-]+", "_", label).strip("_")
    name = time.strftime("rec-%Y%m%d-%H%M%S") + (f"-{safe}" if safe else "") + ".wav"
    write_wav(REC_DIR / name, x, engine.mic.fs)
    return {"name": name, "duration": sec}


app.mount("/recordings", StaticFiles(directory=REC_DIR), name="recordings")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
