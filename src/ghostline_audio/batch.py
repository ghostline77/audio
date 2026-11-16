"""Resumable auditions and explicit reviewed promotion."""

from dataclasses import asdict
import csv
import html
import io
from pathlib import Path
import shutil

from .files import digest, identity, local_path, read_json, write_json
from .voices import Sampling, VoiceEngine, write_audio
from .manifests import load_manifest


def validate_manifest(manifest: dict):
    voices = manifest["voices"]
    seen = set()
    for line in manifest["lines"]:
        identifier = str(line["id"])
        if not identifier.isdecimal() or not 0 < int(identifier) < 2**64:
            raise ValueError(f"Invalid uint64 localization ID: {identifier}")
        gender = line.get("gender", "shared")
        if gender not in {"shared", "female", "male"}:
            raise ValueError(f"Invalid gender binding: {gender}")
        key = (int(identifier), gender)
        if key in seen:
            raise ValueError(f"Duplicate line binding: {key}")
        seen.add(key)
        voice = voices[line["speaker"]]
        if not line["text"].strip() or not (voice.get("full_reference") or voice.get("reference_text", "").strip()):
            raise ValueError(f"Missing spoken text or reference transcript: {identifier}")
        if not isinstance(line.get("instruction", ""), str):
            raise ValueError(f"Instruction must be a string: {identifier}")
    candidates = manifest.get("candidates", 1)
    if not isinstance(candidates, int) or candidates < 1:
        raise ValueError("candidates must be a positive integer")


def render_manifest(path: Path, output: Path, checkpoint: str, device: str = "cuda:0"):
    manifest = load_manifest(path)
    validate_manifest(manifest)
    write_json(output / "resolved-manifest.json", manifest)
    sampling = Sampling(**manifest.get("sampling", {}))
    engine = VoiceEngine(checkpoint, output / "reference-cache", device=device)
    jobs = []
    failures = []
    for line in manifest["lines"]:
        voice = manifest["voices"][line["speaker"]]
        try:
            if voice.get("full_reference"):
                prompt, reference_key, saved_instruction = engine.saved_reference(
                    local_path(path.parent, voice["full_reference"]))
                default_instruction = voice.get("instruction", saved_instruction) or ""
            else:
                prompt, reference_key = engine.reference(
                    local_path(path.parent, voice["reference_audio"]), voice["reference_text"],
                    local_path(path.parent, voice["embedding"]) if voice.get("embedding") else None)
                default_instruction = voice.get("instruction") or ""
            instruction = line.get("instruction", default_instruction)
            for candidate in range(manifest.get("candidates", 1)):
                seed = int(manifest.get("seed", 0)) + candidate
                request = {"line": line, "instruction": instruction,
                           "sampling": asdict(sampling), "seed": seed,
                           "reference": reference_key, "backend": engine.provenance}
                fingerprint = identity(request)
                directory = output / f"{int(line['id']):016X}" / line.get("gender", "shared")
                audio = directory / f"candidate-{candidate + 1:02d}.wav"
                receipt = audio.with_suffix(".json")
                cached = read_json(receipt) if receipt.exists() else {}
                if (cached.get("fingerprint") == fingerprint and audio.exists()
                        and cached.get("audio_sha256") == digest(audio)):
                    result = cached
                    status = "reused"
                else:
                    waveform, rate, timing = engine.generate(
                        line["text"], line.get("language", "English"),
                        instruction, prompt, sampling, seed)
                    write_audio(audio, waveform, rate)
                    result = {"fingerprint": fingerprint, "request": request,
                              "audio_sha256": digest(audio), "sample_rate": rate, "timing": timing}
                    write_json(receipt, result)
                    status = "generated"
                jobs.append({"id": str(line["id"]), "gender": line.get("gender", "shared"),
                             "speaker": line["speaker"], "text": line["text"],
                             "candidate": candidate + 1, "audio": str(audio.resolve()),
                             "audio_sha256": result["audio_sha256"], "fingerprint": fingerprint})
                print(f"{status}: {line['id']} candidate {candidate + 1}", flush=True)
                write_json(output / "report.json", {"jobs": jobs, "failures": failures})
        except Exception as error:
            failures.append({"line": line, "error": str(error)})
            print(f"failed: {line['id']}: {error}", flush=True)
    write_json(output / "report.json", {"jobs": jobs, "failures": failures})
    review_report(output, jobs)
    if failures:
        raise RuntimeError(f"{len(failures)} lines failed; see {output / 'report.json'}")


def review_report(output: Path, jobs: list):
    output.mkdir(parents=True, exist_ok=True)
    selection = output / "selections.csv"
    if not selection.exists():
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["id", "gender", "candidate", "audio_sha256", "approved"])
        for job in jobs:
            writer.writerow([job["id"], job["gender"], job["candidate"], job["audio_sha256"], ""])
        selection.write_text(stream.getvalue(), encoding="utf-8")
    rows = []
    for job in jobs:
        relative = Path(job["audio"]).relative_to(output.resolve()).as_posix()
        rows.append(f"<tr><td>{html.escape(job['id'])}/{job['gender']}</td>"
                    f"<td>{html.escape(job['speaker'])}</td><td>{html.escape(job['text'])}</td>"
                    f"<td>{job['candidate']}</td><td><audio controls src='{html.escape(relative, quote=True)}'>"
                    "</audio></td></tr>")
    (output / "review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Voice auditions</title>"
        "<h1>Voice auditions</h1><p>Mark approved rows in selections.csv after listening.</p>"
        "<table><tr><th>ID/gender</th><th>Speaker</th><th>Text</th><th>Candidate</th><th>Audio</th></tr>"
        + "".join(rows) + "</table>", encoding="utf-8")


def promote(output: Path, selections: Path, destination: Path):
    report = read_json(output / "report.json")
    jobs = {(j["id"], j["gender"], str(j["candidate"])): j for j in report["jobs"]}
    selected = []
    seen = set()
    with selections.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["approved"].strip().lower() not in {"yes", "true", "1"}:
                continue
            key = (row["id"], row["gender"], row["candidate"])
            job = jobs[key]
            binding = key[:2]
            if binding in seen:
                raise ValueError(f"Multiple approved candidates for {binding}")
            seen.add(binding)
            if row["audio_sha256"] != job["audio_sha256"] or digest(Path(job["audio"])) != job["audio_sha256"]:
                raise ValueError(f"Reviewed audio changed: {key}")
            selected.append(job)
    if not selected:
        raise ValueError("No explicitly approved candidates")
    destination.mkdir(parents=True, exist_ok=True)
    for job in selected:
        target = destination / f"{job['gender']}_{int(job['id']):016X}.wav"
        shutil.copyfile(job["audio"], target)
        write_json(target.with_suffix(".json"), {"reviewed": True, **job})
