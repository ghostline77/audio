"""Design an audition, then explicitly adopt its reviewed recording."""

from pathlib import Path
import re
import shutil

from .files import digest, read_json, write_json


def check_speaker(speaker):
    normalized = re.sub(r"[ _-]+", " ", speaker.strip()).casefold()
    if not normalized or normalized in {"v", "v female", "v male", "female v", "male v"}:
        raise ValueError("Voice design requires an NPC name; V uses reviewed clone references")


def design_reference(checkpoint, output, speaker, text, description,
                     language="English", seed=0, device="cuda:0"):
    check_speaker(speaker)
    if not text.strip() or not description.strip():
        raise ValueError("Reference text and voice description are required")
    from .voices import Sampling, VoiceEngine, write_audio
    print("Loading VoiceDesign checkpoint and preparing GPU graphs…", flush=True)
    engine = VoiceEngine(checkpoint, output.parent / "reference-cache", device=device)
    print("Generating reference…", flush=True)
    audio, rate = engine.design(text, language, description, Sampling(), seed)
    write_audio(output, audio[0], rate)
    write_json(output.with_suffix(".json"), {
        "speaker": speaker, "text": text, "description": description,
        "language": language, "seed": seed, "backend": engine.provenance,
        "sha256": digest(output)})
    print(f"Reference ready: {output}", flush=True)


def adopt_reference(audio: Path, library: Path):
    receipt = read_json(audio.with_suffix(".json"))
    speaker = receipt["speaker"].strip()
    check_speaker(speaker)
    if digest(audio) != receipt["sha256"] or not receipt["text"].strip():
        raise ValueError("Design recording changed or its transcript is missing")
    data = read_json(library) if library.exists() else {"schema": "ghostline-voice-library-v1", "voices": {}}
    speaker = next((name for name in data["voices"] if name.casefold() == speaker.casefold()), speaker)
    # Content-addressed recordings keep the old voice usable until the atomic catalogue update.
    slug = re.sub(r"[^a-z0-9]+", "-", speaker.casefold()).strip("-") or "npc"
    relative = Path("designed") / slug / f"{receipt['sha256']}.wav"
    target = library.parent / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(audio, target)
    write_json(target.with_suffix(".json"), receipt)
    data["voices"][speaker] = {"reference_audio": relative.as_posix(),
                               "reference_text": receipt["text"],
                               "selection": {"method": "reviewed VoiceDesign recording"}}
    write_json(library, data)
