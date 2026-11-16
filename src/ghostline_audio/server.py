"""Loopback web workbench. Speech jobs run outside the HTTP process."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import csv
import io
import json
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import sys
import zipfile
from threading import Lock, Thread
from urllib.parse import parse_qs, urlparse

from .files import digest, local_path, read_json, write_json
from .models import MODELS, model_path
from .dialogues import DialogueWorkspace, import_text, review_report


class Workbench:
    def __init__(self, root, library, models=None):
        self.root = root.resolve()
        self.library = library.resolve()
        self.models = models.resolve() if models else self.root / "models"
        self.dialogues = DialogueWorkspace(self.root, self.library)
        self.token = secrets.token_urlsafe(32)
        self.jobs = []
        self.lock = Lock()

    def path(self, value):
        path = local_path(self.root, value)
        if not any(path.is_relative_to(base) for base in (self.root, self.library.parent)):
            raise ValueError("Path must be inside the workspace or voice library")
        return path

    def checkpoint(self, value):
        # User-selected checkpoints may live on another model drive.
        path = local_path(self.root, value)
        if not path.is_dir() or not (path / "config.json").is_file():
            raise ValueError("Choose a downloaded checkpoint folder containing config.json")
        return path

    def voices(self):
        result = []
        for name, voice in read_json(self.library)["voices"].items():
            if voice.get("full_reference"):
                reference = local_path(self.library.parent, voice["full_reference"])
                metadata = read_json(reference)
                audio = local_path(reference.parent, metadata["audio"])
                text = metadata["reference_text"]
            else:
                audio = local_path(self.library.parent, voice["reference_audio"])
                text = voice["reference_text"]
            result.append({"name": name, "audio": str(audio), "text": text,
                           "instruction": voice.get("instruction", ""),
                           "selection": voice.get("selection", {})})
        return result

    def start(self, label, args, metadata=None):
        with self.lock:
            if any(job["status"] == "running" for job in self.jobs):
                raise ValueError("Wait for the current job to finish")
            job = {"id": len(self.jobs) + 1, "label": label, "status": "running", "log": "", **(metadata or {})}
            self.jobs.append(job)

        def run():
            try:
                environment = os.environ.copy()
                environment["PYTHONPATH"] = os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)
                environment["PYTHONIOENCODING"] = "utf-8"
                process = subprocess.Popen([sys.executable, "-u", "-m", "ghostline_audio", *map(str, args)],
                                           cwd=self.root, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                           env=environment)
                for line in process.stdout:
                    with self.lock:
                        job["log"] = (job["log"] + line)[-24000:]
                code = process.wait()
                if code == 0 and job.get("kind") == "export":
                    archive = Path(job["download"])
                    temporary = archive.with_suffix(".writing.zip")
                    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
                        for name in job["files"]:
                            bundle.write(Path(job["destination"]) / name, name)
                    temporary.replace(archive)
                    write_json(Path(job["output"]) / "export.json", {
                        key: job[key] for key in ("destination", "download", "files", "fingerprints")})
                with self.lock:
                    job["status"] = "complete" if code == 0 else "failed"
            except Exception as error:
                with self.lock:
                    job.update(status="failed", log=str(error))
            finally:
                if job.get("kind") == "dialogue":
                    write_json(Path(job["output"]) / "run.json", {
                        key: value for key, value in job.items() if key not in {"log", "id", "label"}})
        Thread(target=run, daemon=True).start()
        return job

    def post(self, route, data):
        if route == "new-dialogue":
            return self.dialogues.create(data["title"])
        if route == "import-dialogue":
            source = self.path(data["path"]) if data.get("path") else None
            value = read_json(source) if source else import_text(data["text"])
            return self.dialogues.create(data.get("title") or value.get("title") or
                                         (source.stem if source else Path(data.get("filename", "Imported dialogue")).stem),
                                         value, source)
        if route == "generate-dialogue":
            path = self.path(data["path"])
            if digest(path) != data["hash"]:
                raise ValueError("This dialogue changed on disk. Open it again before generating")
            checkpoint = self.checkpoint(data.get("checkpoint") or model_path(self.models, "base"))
            run, args = self.dialogues.prepare_run(path, checkpoint)
            try:
                return self.start("Generate dialogue takes", args, run)
            except Exception:
                write_json(Path(run["output"]) / "run.json", {**run, "status": "failed"})
                raise
        if route == "export-dialogue":
            self.post("selections", data)
            output = self.path(data["output"])
            run = read_json(output / "run.json")
            destination = self.path(data["destination"]) if data.get("destination") else (
                self.root / "exports" / Path(run["dialogue"]).stem / output.name)
            destination.mkdir(parents=True, exist_ok=True)
            selected = set(data["fingerprints"])
            jobs = read_json(output / "report.json")["jobs"]
            names = [f"{job['gender']}_{int(job['id']):016X}.wav" for job in jobs if job["fingerprint"] in selected]
            files = [name for wav in names for name in (wav, Path(wav).with_suffix(".json").name)]
            return self.start("Export selected WAVs", ["promote", "--output", output,
                              "--selections", output / "selections.csv", "--destination", destination],
                              {"kind": "export", "destination": str(destination), "files": files,
                               "fingerprints": list(selected),
                               "output": str(output), "download": str(destination / "selected-wavs.zip")})
        if route == "selections":
            output = self.path(data["output"])
            report = read_json(output / "report.json")
            requested = set(data["fingerprints"])
            rows, seen = [], set()
            for job in report["jobs"]:
                if job["fingerprint"] not in requested:
                    continue
                key = (job["id"], job["gender"])
                if key in seen:
                    raise ValueError("Choose one take per line and gender")
                seen.add(key)
                if digest(self.path(job["audio"])) != job["audio_sha256"]:
                    raise ValueError("Audio changed since rendering; render again")
                rows.append([job["id"], job["gender"], job["candidate"], job["audio_sha256"], "yes"])
            if not rows or len(rows) != len(requested):
                raise ValueError("Choose takes from the current report")
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(["id", "gender", "candidate", "audio_sha256", "approved"])
            writer.writerows(rows)
            target = output / "selections.csv"
            temporary = target.with_suffix(".csv.tmp")
            temporary.write_text(stream.getvalue(), encoding="utf-8")
            temporary.replace(target)
            return {"selected": len(rows)}
        if route == "manifest":
            path = self.path(data["path"])
            if path.suffix != ".json":
                raise ValueError("Choose a .json manifest")
            current = digest(path) if path.exists() else None
            if current != data.get("hash"):
                raise ValueError("File changed on disk. Reload before saving")
            from .manifests import assign_ids
            value = assign_ids(data["value"])
            write_json(path, value)
            return {"value": value, "hash": digest(path)}
        if route == "resolve":
            from .manifests import assign_ids
            return assign_ids(data["value"])
        if route == "download":
            model = data["model"]
            return self.start("Download " + model, ["download-model", model, "--output", model_path(self.models, model)])
        if route == "design":
            from .design import check_speaker
            check_speaker(data["speaker"])
            output = self.path(data["output"])
            if output.suffix.lower() != ".wav":
                raise ValueError("Design output must end in .wav")
            return self.start("Design " + data["speaker"], [
                "design", "--checkpoint", self.checkpoint(data["checkpoint"]), "--output", output,
                "--speaker", data["speaker"], "--text", data["text"], "--description", data["description"],
                "--language", data.get("language", "English"), "--seed", int(data.get("seed", 0))])
        if route == "adopt":
            if any(job["status"] == "running" for job in self.jobs):
                raise ValueError("Wait for the current job to finish")
            from .design import adopt_reference
            adopt_reference(self.path(data["audio"]), self.library)
            return {"saved": True}
        if route == "render":
            return self.start("Render dialogue", ["render", self.path(data["manifest"]),
                              "--checkpoint", self.checkpoint(data["checkpoint"]), "--output", self.path(data["output"])])
        if route == "promote":
            return self.start("Promote reviewed takes", ["promote", "--output", self.path(data["output"]),
                              "--selections", self.path(data["selections"]), "--destination", self.path(data["destination"])])
        raise ValueError("Unknown action")


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def parse_request(self):
            if not super().parse_request():
                return False
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(403, "Use the loopback workbench URL")
                return False
            return True

        def send(self, content, kind="application/json", status=200):
            if kind == "application/json":
                content = json.dumps(content, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            try:
                url = urlparse(self.path)
                query = parse_qs(url.query)
                route = url.path
                if route == "/api/bootstrap":
                    self.send({"token": app.token, "workspace": str(app.root), "library": str(app.library),
                               "models": [{"key": key, "name": name, "path": str(model_path(app.models, key)),
                                           "downloaded": (model_path(app.models, key) / "config.json").exists() and
                                           any(model_path(app.models, key).glob("*.safetensors"))}
                                          for key, name in MODELS.items()]})
                elif route == "/api/voices":
                    self.send(app.voices())
                elif route == "/api/dialogues":
                    self.send(app.dialogues.list())
                elif route == "/api/dialogue":
                    self.send(app.dialogues.document(app.path(query["path"][0])))
                elif route == "/api/runs":
                    self.send(app.dialogues.runs(query.get("dialogue", [None])[0]))
                elif route == "/api/review":
                    self.send(review_report(app.path(query["output"][0])))
                elif route == "/api/download":
                    path = app.path(query["path"][0])
                    if path.suffix.lower() != ".zip":
                        raise ValueError("Choose a WAV export archive")
                    self.send(path.read_bytes(), "application/zip")
                elif route == "/api/jobs":
                    with app.lock:
                        self.send(app.jobs)
                elif route == "/api/manifest":
                    path = app.path(query["path"][0])
                    value = read_json(path)
                    if "lines" in value:
                        from .manifests import assign_ids
                        value = assign_ids(value)
                    self.send({"value": value, "hash": digest(path)})
                elif route == "/api/media":
                    path = app.path(query["path"][0])
                    if path.suffix.lower() not in {".wav", ".csv"}:
                        raise ValueError("Unsupported preview type")
                    content = path.read_bytes()
                    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    self.send(content, kind)
                elif route in {"/", "/comparisons"}:
                    self.send((Path(__file__).parent / "ui/index.html").read_bytes(), "text/html; charset=utf-8")
                elif route in {"/assets/app.js", "/assets/style.css"}:
                    path = Path(__file__).parent / "ui" / route.lstrip("/")
                    self.send(path.read_bytes(), "text/javascript" if path.suffix == ".js" else "text/css")
                else:
                    self.send({"error": "Not found"}, status=404)
            except (ValueError, KeyError, OSError) as error:
                self.send({"error": str(error)}, status=400)

        def do_POST(self):
            try:
                if not secrets.compare_digest(self.headers.get("X-Audio-Token", ""), app.token):
                    self.send({"error": "Reload the workbench"}, status=403)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2_000_000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(size))
                self.send(app.post(self.path.removeprefix("/api/"), data))
            except (ValueError, KeyError, OSError, TypeError) as error:
                self.send({"error": str(error)}, status=400)

        def log_message(self, *_):
            pass
    return Handler


def serve(root, library, port, models=None):
    app = Workbench(root, library, models)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"Audio workbench: http://127.0.0.1:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
