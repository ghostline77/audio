"""Managed dialogue documents; the UI never needs a hand-written manifest."""

import copy
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid

from .files import digest, local_path, read_json, write_json
from .manifests import assign_ids, load_manifest


def relative_path(path, directory):
    try:
        return Path(os.path.relpath(path, directory)).as_posix()
    except ValueError:
        return str(path)


class DialogueWorkspace:
    def __init__(self, root, library):
        self.root = root
        self.library = library
        self.directory = root / "dialogues"

    def create(self, title, value=None, source=None):
        if not isinstance(title, str):
            raise ValueError("Give your dialogue a name")
        title = title.strip()
        if not title or len(title) > 100:
            raise ValueError("Give your dialogue a name (1–100 characters)")
        identifier = uuid.uuid4().hex
        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or "dialogue"
        path = self.directory / f"{slug}-{identifier[:8]}.json"
        value = copy.deepcopy(value) if value is not None else {
            "namespace": f"audio.{identifier}", "seed": 42, "candidates": 2, "lines": []}
        if not isinstance(value, dict):
            raise ValueError("Choose a dialogue JSON object")
        if "lines" not in value and isinstance(value.get("spoken_lines"), list):
            value["lines"] = [{**line, **({"id": line["string_id"]} if "string_id" in line else {})}
                              for line in value.pop("spoken_lines")]
            for line in value["lines"]:
                line.pop("string_id", None)
        if not isinstance(value.get("lines"), list):
            raise ValueError("This file has no dialogue lines. Import a dialogue JSON with lines or spoken_lines")
        if not all(isinstance(line, dict) for line in value["lines"]):
            raise ValueError("Every dialogue line needs a speaker and text")
        value.setdefault("namespace", f"audio.{identifier}")
        used_keys = {line.get("key") for line in value["lines"]}
        for index, line in enumerate(value["lines"]):
            if "key" not in line:
                key = f"imported-{index + 1}"
                while key in used_keys:
                    key += "-import"
                line["key"] = key
                used_keys.add(key)
        for voice in value.get("voices", {}).values():
            for field in ("reference_audio", "full_reference", "embedding", "reference_codes"):
                if voice.get(field):
                    if source is None and not Path(voice[field]).is_absolute():
                        raise ValueError("This file uses relative voice assets. Open it by workspace path in the import options")
                    voice[field] = str(local_path(source.parent if source else self.root, voice[field]))
        if source is not None and value.get("voice_library"):
            library = local_path(source.parent, value["voice_library"])
        else:
            library = self.library
        value["voice_library"] = relative_path(library, path.parent)
        value["title"] = title
        value.setdefault("candidates", 2)
        value = assign_ids(value)
        write_json(path, value)
        return self.document(path)

    def document(self, path):
        value = read_json(path)
        if "lines" not in value:
            raise ValueError("This is not an audio dialogue document")
        return {"path": str(path.relative_to(self.root)), "value": assign_ids(value), "hash": digest(path)}

    def list(self):
        documents = []
        for path in self.directory.glob("*.json"):
            try:
                value = read_json(path)
                documents.append({"path": str(path.relative_to(self.root)), "title": value.get("title", path.stem),
                                  "lines": len(value.get("lines", [])), "modified": path.stat().st_mtime})
            except (OSError, ValueError, TypeError):
                continue
        return sorted(documents, key=lambda item: item["modified"], reverse=True)

    def prepare_run(self, path, checkpoint):
        manifest = load_manifest(path)
        if not manifest["lines"]:
            raise ValueError("Add a line before generating audio")
        takes = manifest.get("candidates", 2)
        if isinstance(takes, bool) or not isinstance(takes, int) or not 1 <= takes <= 5:
            raise ValueError("Choose between 1 and 5 takes per line")
        for index, line in enumerate(manifest["lines"], 1):
            if not line.get("text", "").strip():
                raise ValueError(f"Line {index}: write the words to speak")
            if line.get("speaker") not in manifest.get("voices", {}):
                raise ValueError(f"Line {index}: choose a voice from the cast")
            if line.get("gender", "shared") not in {"shared", "female", "male"}:
                raise ValueError(f"Line {index}: choose a valid audio binding")
        output = self.root / "work/dialogues" / path.stem / uuid.uuid4().hex[:12]
        manifest.pop("voice_library", None)  # load_manifest resolved the complete cast.
        write_json(output / "render-input.json", manifest)
        run = {"kind": "dialogue", "dialogue": str(path.relative_to(self.root)),
               "title": manifest.get("title", path.stem), "output": str(output),
               "checkpoint": str(checkpoint), "status": "running", "lines": len(manifest["lines"]),
               "takes": takes, "created": datetime.now(timezone.utc).isoformat()}
        write_json(output / "run.json", run)
        return run, ["render", output / "render-input.json", "--checkpoint", checkpoint, "--output", output]

    def runs(self, document=None):
        rows = []
        for path in (self.root / "work/dialogues").glob("*/*/run.json"):
            try:
                run = read_json(path)
                if document is None or run["dialogue"] == document:
                    rows.append(run)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(rows, key=lambda run: run["created"], reverse=True)


def review_report(output):
    report = read_json(output / "report.json")
    selected = set()
    selection = output / "selections.csv"
    if selection.exists():
        with selection.open(encoding="utf-8-sig", newline="") as stream:
            selected = {(row["id"], row["gender"], row["candidate"], row["audio_sha256"])
                        for row in csv.DictReader(stream) if row["approved"].strip().lower() in {"yes", "true", "1"}}
    fingerprints = [job["fingerprint"] for job in report["jobs"]
                    if (job["id"], job["gender"], str(job["candidate"]), job["audio_sha256"]) in selected]
    exported = read_json(output / "export.json") if (output / "export.json").exists() else None
    if exported and (set(exported["fingerprints"]) != set(fingerprints) or not Path(exported["download"]).is_file()):
        exported = None
    return {**report, "selected": fingerprints, "export": exported}


def import_text(text):
    try:
        value = json.loads(text)
    except ValueError as error:
        raise ValueError("This file is not valid JSON. Choose an exported dialogue file") from error
    if not isinstance(value, dict):
        raise ValueError("Choose a dialogue JSON object with a lines array")
    return value
