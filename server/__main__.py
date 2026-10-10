"""Start the live demo:  .venv\\Scripts\\python -m server  [--port 8000] [--device ID] [--no-browser]"""
import argparse
import threading
import webbrowser

import uvicorn

from .app import app


def main():
    p = argparse.ArgumentParser(description="Guitar FFT note & chord detector (live demo)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--device", type=int, default=None, help="input device id (see /api/devices)")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()

    app.state.device = args.device
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    print(f"Open {url}   (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
