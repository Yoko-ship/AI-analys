"""Poll only the video queue; record public pages and upload the leased export."""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import socket
import subprocess
import threading
import time

import requests

from marketing.video_contract import Storyboard
from .render import assemble, command, duration

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("uzstock.video")


class Worker:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.url = self.config["server"].rstrip("/") + "/api/marketing-video-worker"
        if not self.url.startswith("https://"):
            raise ValueError("Video queue requires HTTPS")
        self.headers = {"Authorization": "Bearer " + self.config["token"]}

    def post(self, path, **kwargs):
        response = requests.post(self.url + path, headers=self.headers, timeout=(15, 180), **kwargs)
        if not response.ok:
            raise RuntimeError(f"Video queue returned HTTP {response.status_code}")
        return response.json()

    def render(self, job):
        storyboard = Storyboard.model_validate(job["storyboard"]).model_dump()
        folder = Path(self.config["output_directory"]) / (job["id"] + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
        stage = ["narration"]
        stopped, cancelled = threading.Event(), threading.Event()
        body = {"lease_token": job["lease_token"], "stage": "narration"}

        def progress(value):
            if cancelled.is_set():
                raise RuntimeError("Video lease is no longer available")
            stage[0] = value
            self.post(f'/{job["id"]}/progress', json={**body, "stage": value})
            log.info("Video stage: %s", value)

        def heartbeat():
            failures = 0
            while not stopped.wait(60):
                try:
                    self.post(f'/{job["id"]}/progress', json={**body, "stage": stage[0]})
                    failures = 0
                except Exception:
                    failures += 1
                    if failures >= 3:
                        cancelled.set()

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            progress("narration")
            with (folder / "voice.log").open("wb") as output:
                subprocess.run([self.config["qwen_python"], str(ROOT / "video_worker/qwen_voice.py"),
                                str(self.config_path), str(folder)], stdout=output, stderr=subprocess.STDOUT,
                               check=True, timeout=2400)
            progress("capturing")
            command(["node", str(ROOT / "video_worker/capture.mjs"), str(folder)], cwd=ROOT, timeout=600)
            for index in range(len(storyboard["scenes"])):
                source = folder / f"capture-{index}.webm"
                start = max(0, duration(source) - 8)
                command(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-i", str(source), "-t", "8",
                         "-an", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "6",
                         str(folder / f"site-{index}.webm")])
            output = assemble(storyboard, folder, progress)
            progress("uploading")
            with output.open("rb") as stream:
                offset = 0
                while chunk := stream.read(512000):
                    for attempt in range(3):
                        try:
                            response = requests.post(self.url + f'/{job["id"]}/chunk', data=chunk,
                                headers={**self.headers, "X-Video-Lease": job["lease_token"], "X-Video-Offset": str(offset),
                                         "Content-Type": "application/octet-stream"}, timeout=(15, 60))
                            response.raise_for_status()
                            if response.json()["offset"] != offset + len(chunk):
                                raise ValueError("Video upload offset mismatch")
                            break
                        except (requests.RequestException, ValueError):
                            if attempt == 2:
                                raise RuntimeError("Video chunk upload failed") from None
                            time.sleep(2 ** attempt)
                    offset += len(chunk)
            self.post(f'/{job["id"]}/complete', json={**body, "stage": "uploading"})
            log.info("Video completed and uploaded")
        except Exception:
            log.exception("Video failed; local project retained at %s", folder)
            try:
                self.post(f'/{job["id"]}/fail', json={**body, "stage": stage[0]})
            except Exception:
                log.error("Failure could not be acknowledged; the server will recover its lease")
        finally:
            stopped.set()
            thread.join(timeout=1)

    def tick(self):
        job = self.post("/claim").get("job")
        if job:
            self.render(job)
        return bool(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        filename=args.config.resolve().parent / "worker.log", encoding="utf-8")
    worker = Worker(args.config)
    with socket.socket() as singleton:
        singleton.bind(("127.0.0.1", 48379))
        while True:
            try:
                worker.tick()
            except Exception:
                log.exception("Video queue unavailable; retrying in 15 seconds")
                if args.once:
                    raise
            if args.once:
                return
            time.sleep(15)


if __name__ == "__main__":
    main()
