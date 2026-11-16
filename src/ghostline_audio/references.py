"""Import saved full-reference prompts without loading a speech model."""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
from safetensors.numpy import load_file, save_file

from .files import digest, identity, local_path, read_json, write_json


def codec_frames(path: Path) -> np.ndarray:
    value = read_json(path)
    expected = {"schema_version": 1, "model": "qwen3_tts", "kind": "codec_frames",
                "layout": "frames_code_groups"}
    if any(value.get(key) != item for key, item in expected.items()):
        raise ValueError(f"Unsupported saved codec format: {path}")
    frames, groups = value["frame_count"], value["code_groups"]
    values = value["values"]
    if (not isinstance(frames, int) or frames < 1 or not isinstance(groups, int) or groups < 1
            or len(values) != frames * groups
            or any(type(item) is not int or not 0 <= item < 2**31 for item in values)):
        raise ValueError(f"Invalid saved codec dimensions or tokens: {path}")
    return np.asarray(values, dtype=np.int64).reshape(frames, groups)


def embedding_vector(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".json":
        source = read_json(path)
        if (source.get("schema_version") != 1 or source.get("model") != "qwen3_tts"
                or source.get("kind") != "speaker_embedding"):
            raise ValueError(f"Unsupported speaker embedding format: {path}")
        vector = np.asarray(source["values"], dtype=np.float32)
    else:
        tensors = load_file(str(path))
        vector = tensors.get("speaker_embedding", tensors.get("embedding"))
    if vector is None or vector.ndim != 1 or not len(vector) or not np.isfinite(vector).all():
        raise ValueError(f"Invalid speaker embedding: {path}")
    return np.asarray(vector, dtype=np.float32)


def import_embedding(record: dict, base: Path, output: Path) -> dict:
    source = local_path(base, record["embedding"])
    vector = embedding_vector(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = load_file(str(output)).get("speaker_embedding") if output.exists() else None
    if existing is None or not np.array_equal(existing, vector):
        save_file({"speaker_embedding": vector}, str(output))
    return {"file": output.name, "dimensions": len(vector), "sha256": digest(output),
            "source_sha256": digest(source), "mode": "embedding_only"}


def import_reference(record: dict, base: Path, output: Path) -> dict:
    text = record["reference_text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A full reference needs its exact transcript")
    sources = {key: local_path(base, record[key]) for key in ("embedding", "codes", "audio")}
    source_hashes = {key: digest(path) for key, path in sources.items()}
    fingerprint = identity({"sources": source_hashes, "text": text,
                            "instruction": record.get("instruction") or "",
                            "selection": record.get("selection", {})})
    metadata_path = output / "reference.json"
    if metadata_path.exists():
        existing = read_json(metadata_path)
        assets_match = all((output / name).is_file() and digest(output / name) == sha
                           for name, sha in existing["sha256"].items())
        if (assets_match and existing.get("source_sha256") == source_hashes
                and existing.get("reference_text") == text):
            existing.update(fingerprint=fingerprint,
                            instruction=record.get("instruction") or "",
                            selection=record.get("selection", {}))
            write_json(metadata_path, existing)
            return existing
        raise ValueError(f"Reference already exists with different contents: {output}")
    vector = embedding_vector(sources["embedding"])
    codes = codec_frames(sources["codes"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        save_file({"speaker_embedding": np.asarray(vector, dtype=np.float32),
                   "ref_code": codes}, str(staging / "reference.safetensors"))
        shutil.copyfile(sources["audio"], staging / "reference.wav")
        metadata = {"schema": "ghostline-voice-reference-v1", "fingerprint": fingerprint,
                    "speaker": record["speaker"], "variant": record["variant"],
                    "mode": "full_reference", "reference_text": text,
                    "instruction": record.get("instruction") or "",
                    "tensors": "reference.safetensors", "audio": "reference.wav",
                    "frame_count": len(codes), "code_groups": codes.shape[1],
                    "sha256": {name: digest(staging / name)
                               for name in ("reference.safetensors", "reference.wav")},
                    "source_sha256": source_hashes,
                    "selection": record.get("selection", {})}
        write_json(staging / "reference.json", metadata)
        os.replace(staging, output)
    return metadata


def import_library(manifest_path: Path, output: Path, report_path: Path | None = None) -> None:
    manifest = read_json(manifest_path)
    voices = {}
    embedding_variants = {}
    failures = []
    names = set()
    targets = set()
    for record in manifest["references"] + manifest.get("embeddings", []):
        for key in ("speaker", "variant"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", record[key]):
                raise ValueError(f"Invalid reference {key}: {record[key]}")
        target_key = (record["speaker"], "embedding" if record.get("embedding_only") else "full_reference", record["variant"])
        if record["name"] in names or target_key in targets:
            raise ValueError(f"Duplicate library reference: {record['name']}")
        names.add(record["name"])
        targets.add(target_key)
    with ThreadPoolExecutor() as executor:
        pending = {executor.submit(import_reference, record, manifest_path.parent,
                                   output / record["speaker"] / record["variant"]): record
                   for record in manifest["references"]}
        pending.update({executor.submit(import_embedding, record, manifest_path.parent,
                                        output / record["speaker"] / "embeddings" / f"{record['variant']}.safetensors"): record
                        for record in manifest.get("embeddings", [])})
        for future in as_completed(pending):
            record = pending[future]
            try:
                metadata = future.result()
                if record.get("embedding_only"):
                    metadata["file"] = f"{record['speaker']}/embeddings/{record['variant']}.safetensors"
                    embedding_variants[record["name"]] = metadata
                    print(f"Imported embedding variant: {record['name']}", flush=True)
                    continue
                target = Path(record["speaker"]) / record["variant"] / "reference.json"
                voices[record["name"]] = {"full_reference": target.as_posix(),
                                          "instruction": metadata["instruction"],
                                          "selection": metadata.get("selection", {})}
                print(f"Imported full reference: {record['name']}", flush=True)
            except Exception as error:
                failures.append({"name": record.get("name"), "error": str(error)})
    write_json(output / "voices.json", {"schema": "ghostline-voice-library-v1",
                                        "voices": dict(sorted(voices.items())),
                                        "embedding_variants": dict(sorted(embedding_variants.items()))})
    report_path = report_path or output.parent / "work" / "reference-import-report.json"
    write_json(report_path, {"references": len(voices),
                             "embedding_variants": len(embedding_variants), "failures": failures})
    if failures:
        raise RuntimeError(f"{len(failures)} reference imports failed; see {report_path}")
