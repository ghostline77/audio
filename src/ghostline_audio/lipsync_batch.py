"""Resumable facial-curve generation with one resident aligner and curve model."""

from pathlib import Path
import shutil
import subprocess

from .alignment import PhoneAligner
from .curves import synthesize
from .files import digest, read_json, write_json


def generate_batch(manifest: Path, model: Path, output: Path, device: str = "cuda:0"):
    """Generate named facial curves from explicit WAV, transcript and gender bindings."""
    inputs = read_json(manifest)["lines"]
    template = read_json(model)
    model_hash = digest(model)
    aligner = PhoneAligner(device=device)
    jobs, failures = [], []
    names = set()
    for line in inputs:
        try:
            identity = int(line["id"])
            gender = line["gender"]
            if not 0 < identity < 2**64 or gender not in {"female", "male"}:
                raise ValueError("Require uint64 line ID and female/male facial gender")
            name = f"{gender[0]}_{identity:016X}"
            if name in names:
                raise ValueError(f"Duplicate animation {name}")
            names.add(name)
            audio = Path(line["audio"])
            if not audio.is_absolute():
                audio = manifest.parent / audio
            audio_hash = digest(audio)
            target = output / f"{name}.json"
            cached = read_json(target) if target.exists() else {}
            if (cached.get("audio_sha256") == audio_hash
                    and cached.get("model_sha256") == model_hash
                    and cached.get("text") == line["text"]):
                status = "reused"
            else:
                alignment = aligner.align(audio, line["text"])
                curves = synthesize(template, alignment, device=device)
                write_json(target, {"schema": "ghostline-facial-curves-v1", "name": name,
                           "locstring": str(identity), "text": line["text"],
                           "audio_sha256": audio_hash, "model_sha256": model_hash,
                           "alignment": alignment, **curves})
                status = "generated"
            jobs.append({"name": name, "curves": str(target.resolve())})
            print(f"{status}: {name}", flush=True)
        except Exception as error:
            failures.append({"line": line, "error": str(error)})
            print(f"failed: {line.get('id')}: {error}", flush=True)
        write_json(output / "report.json", {"jobs": jobs, "failures": failures})
    if failures:
        raise RuntimeError(f"{len(failures)} lipsync lines failed; see {output / 'report.json'}")


def export_native(curves: Path, output: Path, game: Path, schema: Path | None, rig: str,
                  exporter: Path | None = None):
    """Finish the audio pipeline through the shared native resource writer."""
    if exporter is None:
        sibling = Path(__file__).resolve().parents[3] / "ghostline-red" / "target"
        candidates = [sibling / profile / "ghostline-facial.exe" for profile in ("release", "debug")]
        exporter = next((path for path in candidates if path.is_file()), None)
        if exporter is None:
            located = shutil.which("ghostline-facial")
            exporter = Path(located) if located else None
    if exporter is None:
        raise FileNotFoundError("Native facial writer is unavailable; build ghostline-red's ghostline-facial binary or pass --native-exporter")
    command = [str(exporter), "--game", str(game),
               "--rig", rig, "--curves", str(curves), "--output", str(output)]
    if schema is not None:
        command.extend(["--schema", str(schema)])
    subprocess.run(command, check=True)
