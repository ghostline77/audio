"""Render new references and rejected baselines with matched text and seeds."""

import argparse
from dataclasses import asdict
from pathlib import Path

import soundfile as sf

from ghostline_audio.files import digest, identity, read_json, write_json
from ghostline_audio.voices import Sampling, VoiceEngine, write_audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    sampling = Sampling(**manifest["sampling"])
    print("Loading Base checkpoint…", flush=True)
    engine = VoiceEngine(args.checkpoint, args.output / "reference-cache")
    comparison = {**manifest, "backend": engine.provenance, "items": []}
    for item in manifest["items"]:
        entry = dict(item)
        for variant in ("new", "previous"):
            if variant == "new":
                reference_audio = Path(item["reference_audio"])
                prompt, key = engine.reference(reference_audio, item["reference_text"])
            else:
                reference = Path(item["previous_reference"])
                prompt, key, _ = engine.saved_reference(reference)
                metadata = read_json(reference)
                entry["previous_reference_audio"] = str(reference.parent / metadata["audio"])
                entry["previous_reference_text"] = metadata["reference_text"]
            request = {"text": manifest["target_text"], "language": "English", "instruction": "",
                       "seed": item["seed"], "sampling": asdict(sampling),
                       "reference": key, "backend": engine.provenance}
            fingerprint = identity(request)
            audio = args.output / "samples" / f"{item['key']}-{variant}.wav"
            receipt = audio.with_suffix(".json")
            cached = read_json(receipt) if receipt.exists() else {}
            if not (audio.exists() and cached.get("fingerprint") == fingerprint
                    and cached.get("sha256") == digest(audio)):
                print(f"Rendering {item['key']} / {variant} / seed {item['seed']}…", flush=True)
                waveform, rate, timing = engine.generate(manifest["target_text"], "English", "",
                                                         prompt, sampling, item["seed"])
                write_audio(audio, waveform, rate)
                write_json(receipt, {"fingerprint": fingerprint, "sha256": digest(audio),
                                     "request": request, "timing": timing})
            else:
                print(f"Reused {item['key']} / {variant}", flush=True)
            info = sf.info(audio)
            entry[variant + "_sample"] = str(audio.resolve())
            entry[variant + "_sha256"] = digest(audio)
            entry[variant + "_seconds"] = info.duration
        comparison["items"].append(entry)
        write_json(args.output / "comparison.json", comparison)
    print(f"Ready: {args.output / 'comparison.json'}", flush=True)


if __name__ == "__main__":
    main()
