"""Stable dialogue identities, independent of speech-model dependencies."""

import copy

from .files import local_path, read_json


def assign_ids(manifest: dict) -> dict:
    """Preserve explicit IDs; derive missing IDs from namespace + stable line key."""
    result = copy.deepcopy(manifest)
    namespace = result.get("namespace", "")
    for line in result["lines"]:
        if "id" not in line:
            key = line.get("key", "")
            if not isinstance(namespace, str) or not namespace.strip() or not isinstance(key, str) or not key.strip():
                raise ValueError("Lines without id require a manifest namespace and a stable key")
            # Match the original prepare_vanilla_voices.string_id FNV-1a routine.
            identifier = 0xcbf29ce484222325
            for byte in f"{namespace}:{key}".encode("utf-8"):
                identifier = ((identifier ^ byte) * 0x100000001b3) & (2**64 - 1)
            line["id"] = str(identifier or 1)
        identifier = line["id"]
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier).isascii() or not str(identifier).isdecimal() or not 0 < int(identifier) < 2**64:
            raise ValueError(f"Invalid uint64 localization ID: {identifier}")
        line["id"] = str(int(identifier))
    bindings = [(line["id"], line.get("gender", "shared")) for line in result["lines"]]
    if len(bindings) != len(set(bindings)):
        raise ValueError("Duplicate localization ID/gender binding")
    return result


def load_manifest(path):
    manifest = assign_ids(read_json(path))
    for voice in manifest.get("voices", {}).values():
        for field in ("full_reference", "reference_audio", "embedding", "reference_codes"):
            if voice.get(field):
                voice[field] = str(local_path(path.parent, voice[field]))
    if manifest.get("voice_library"):
        library_path = local_path(path.parent, manifest["voice_library"])
        voices = read_json(library_path)["voices"]
        for voice in voices.values():
            for field in ("full_reference", "reference_audio", "embedding", "reference_codes"):
                if voice.get(field):
                    voice[field] = str(local_path(library_path.parent, voice[field]))
        manifest["voices"] = {**voices, **manifest.get("voices", {})}
    return manifest
