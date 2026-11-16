from pathlib import Path

import pytest

from ghostline_audio.dialogues import DialogueWorkspace, import_text, review_report
from ghostline_audio.files import read_json, write_json
from ghostline_audio.manifests import assign_ids


def workspace(tmp_path):
    library = tmp_path / "voices/voices.json"
    write_json(library, {"voices": {"Judy": {"reference_audio": "judy.wav", "reference_text": "Hello"}}})
    return DialogueWorkspace(tmp_path, library)


def test_new_dialogue_needs_only_a_name_and_keeps_identity(tmp_path):
    store = workspace(tmp_path)
    doc = store.create("First meeting")
    assert doc["value"]["title"] == "First meeting"
    assert doc["value"]["voice_library"] == "../voices/voices.json"
    assert doc["value"]["candidates"] == 2
    doc["value"]["lines"] = [{"key": "greeting", "speaker": "Judy", "text": "Hello"}]
    first = assign_ids(doc["value"])
    doc["value"]["title"] = "A different display name"
    doc["value"]["lines"][0]["text"] = "Different words"
    assert assign_ids(doc["value"])["lines"][0]["id"] == first["lines"][0]["id"]
    assert store.list()[0]["path"] == doc["path"]


def test_import_preserves_unsigned_quest_ids_and_reference_paths(tmp_path):
    store = workspace(tmp_path)
    source = tmp_path / "quests/q001/lines.json"
    data = {"spoken_lines": [{"string_id": 2**64 - 1, "speaker": "Judy", "text": "Hello"}],
            "voices": {"Judy": {"reference_audio": "voice/ref.wav", "reference_text": "Hello"}}}
    doc = store.create("Imported scene", data, source)
    assert doc["value"]["lines"][0]["id"] == str(2**64 - 1)
    assert "string_id" not in doc["value"]["lines"][0]
    assert doc["value"]["voices"]["Judy"]["reference_audio"] == str((source.parent / "voice/ref.wav").resolve())
    with pytest.raises(ValueError, match="relative voice assets"):
        store.create("Upload without a directory", data)


def test_generation_freezes_the_dialogue_and_resolves_library(tmp_path):
    store = workspace(tmp_path)
    doc = store.create("Test scene", {"lines": [{"key": "greeting", "speaker": "Judy", "text": "First version"}], "candidates": 2})
    path = tmp_path / doc["path"]
    run, args = store.prepare_run(path, tmp_path / "base")
    snapshot = Path(run["output"]) / "render-input.json"
    value = read_json(path)
    value["lines"][0]["text"] = "Edited during generation"
    write_json(path, value)
    generated = read_json(snapshot)
    assert generated["lines"][0]["text"] == "First version"
    assert Path(generated["voices"]["Judy"]["reference_audio"]).is_absolute()
    assert "voice_library" not in generated
    assert args[1] == snapshot
    assert store.runs()[0]["takes"] == 2


def test_generation_reports_actionable_line_errors(tmp_path):
    store = workspace(tmp_path)
    doc = store.create("Missing words", {"lines": [{"key": "one", "speaker": "Judy", "text": ""}]})
    with pytest.raises(ValueError, match="Line 1: write the words"):
        store.prepare_run(tmp_path / doc["path"], tmp_path / "base")
    with pytest.raises(ValueError, match="valid JSON"):
        import_text("{broken")


def test_reopening_review_restores_only_hash_matched_choices(tmp_path):
    write_json(tmp_path / "report.json", {"jobs": [
        {"id": "18446744073709551615", "gender": "shared", "candidate": 2,
         "audio_sha256": "current", "fingerprint": "selected"}], "failures": []})
    (tmp_path / "selections.csv").write_text(
        "id,gender,candidate,audio_sha256,approved\n18446744073709551615,shared,2,current,yes\n", encoding="utf-8")
    assert review_report(tmp_path)["selected"] == ["selected"]
    archive = tmp_path / "selected-wavs.zip"
    archive.write_bytes(b"export")
    write_json(tmp_path / "export.json", {"fingerprints": ["selected"], "download": str(archive)})
    assert review_report(tmp_path)["export"]["download"] == str(archive)
    (tmp_path / "selections.csv").write_text(
        "id,gender,candidate,audio_sha256,approved\n18446744073709551615,shared,2,stale,yes\n", encoding="utf-8")
    assert review_report(tmp_path)["selected"] == []
    assert review_report(tmp_path)["export"] is None
