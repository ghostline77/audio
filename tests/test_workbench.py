import csv
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ghostline_audio.design import adopt_reference, check_speaker
from ghostline_audio.files import digest, read_json, write_json
from ghostline_audio.manifests import assign_ids, load_manifest
from ghostline_audio.server import Workbench, make_handler


def test_ids_stable_on_text_edit_and_reorder():
    original = {"namespace": "quest", "lines": [
        {"key": "one", "text": "Hello"}, {"key": "two", "text": "Goodbye"}]}
    first = assign_ids(original)
    original["lines"].reverse()
    original["lines"][1]["text"] = "Changed"
    second = assign_ids(original)
    assert first["lines"][0]["id"] == second["lines"][1]["id"]
    assert int(first["lines"][0]["id"]) != int(first["lines"][1]["id"])
    assert "id" not in original["lines"][0]
    assert assign_ids({"namespace": "example.q001", "lines": [{"key": "line-001"}]} )["lines"][0]["id"] == "11341756592957569315"


def test_resolved_inline_paths_survive_relocation(tmp_path):
    source = tmp_path / "source/input.json"
    write_json(source, {"namespace": "quest", "voices": {
        "NPC": {"reference_audio": "reference.wav", "reference_text": "Hello"}},
        "lines": [{"key": "hello", "speaker": "NPC", "text": "Hello"}]})
    resolved = load_manifest(source)
    moved = tmp_path / "output/resolved.json"
    write_json(moved, resolved)
    assert load_manifest(moved) == resolved
    assert resolved["voices"]["NPC"]["reference_audio"] == str((source.parent / "reference.wav").resolve())


def test_explicit_uint64_and_gender_bindings():
    result = assign_ids({"lines": [{"id": 2**64-1, "gender": "male"},
                                   {"id": str(2**64-1), "gender": "female"}]})
    assert result["lines"][0]["id"] == "18446744073709551615"
    with pytest.raises(ValueError):
        assign_ids({"lines": [{"id": "01"}, {"id": 1}]})
    for value in [True, 0, -1, 2**64, 1.5, "１２"]:
        with pytest.raises(ValueError):
            assign_ids({"lines": [{"id": value}]})


def test_adoption_replaces_one_voice_and_checks_recording(tmp_path):
    audio = tmp_path / "design.wav"
    audio.write_bytes(b"reviewed recording")
    write_json(audio.with_suffix(".json"), {"speaker": "IRIS", "text": "Hello", "sha256": digest(audio)})
    library = tmp_path / "voices/voices.json"
    write_json(library, {"voices": {"Iris": {"reference_text": "old"}, "Judy": {"reference_text": "keep"}}})
    adopt_reference(audio, library)
    assert set(read_json(library)["voices"]) == {"Iris", "Judy"}
    voice = read_json(library)["voices"]["Iris"]
    assert (library.parent / voice["reference_audio"]).read_bytes() == audio.read_bytes()
    assert voice["reference_text"] == "Hello"
    audio.write_bytes(b"changed")
    with pytest.raises(ValueError):
        adopt_reference(audio, library)


@pytest.mark.parametrize("name", ["V", "v-male", "V Female", "v_female", ""])
def test_no_design_for_v(name):
    with pytest.raises(ValueError):
        check_speaker(name)


def test_selection_binds_audio_and_rejects_multiple_takes(tmp_path):
    app = Workbench(tmp_path, tmp_path / "voices.json")
    output = tmp_path / "takes"
    output.mkdir()
    audio = output / "take.wav"
    audio.write_bytes(b"take")
    jobs = [{"id": "18446744073709551615", "gender": "shared", "candidate": i,
             "fingerprint": str(i), "audio": str(audio), "audio_sha256": digest(audio)} for i in [1, 2]]
    write_json(output / "report.json", {"jobs": jobs})
    with pytest.raises(ValueError):
        app.post("selections", {"output": "takes", "fingerprints": ["1", "2"]})
    app.post("selections", {"output": "takes", "fingerprints": ["2"]})
    with (output / "selections.csv").open(newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["id"] == "18446744073709551615"
    assert row["candidate"] == "2"
    audio.write_bytes(b"changed")
    with pytest.raises(ValueError):
        app.post("selections", {"output": "takes", "fingerprints": ["2"]})


def test_http_token_disk_conflict_and_browser_uint64(tmp_path):
    library = tmp_path / "voices.json"
    write_json(library, {"voices": {}})
    app = Workbench(tmp_path, library)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert urlopen(base).status == 200
        write_json(tmp_path / "input.json", {"lines": [{"id": 2**64-1}]})
        result = json.load(urlopen(base + "/api/manifest?path=input.json"))
        assert result["value"]["lines"][0]["id"] == "18446744073709551615"
        body = json.dumps({"path": "input.json", "value": result["value"], "hash": "stale"}).encode()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/manifest", data=body))
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/manifest", data=body, headers={"X-Audio-Token": app.token}))
        assert error.value.code == 400
        with pytest.raises(ValueError):
            app.path("../outside.json")
    finally:
        server.shutdown()
        server.server_close()


def test_active_catalogue_has_one_entry_per_character():
    root = Path(__file__).resolve().parents[1]
    voices = read_json(root / "voices/voices.json")["voices"]
    assert len(voices) == 15
    assert not any(" Reference " in name for name in voices)
    for speaker in ["Judy", "Panam", "Songbird"]:
        assert voices[speaker]["full_reference"] == f"{speaker.lower()}/reviewed-2026-11-05/reference.json"
        assert voices[speaker]["instruction"] == ""
        assert voices[speaker]["selection"]["reference"] == 2
    choices = {"Johnny": 1, "Jackie": 1, "Viktor": 1, "Takemura": 1,
               "River": 1, "Kerry": 2, "Reed": 1, "Placide": 1}
    for speaker, reference in choices.items():
        assert voices[speaker]["full_reference"] == f"{speaker.lower()}/neutral-{reference}/reference.json"
        assert voices[speaker]["instruction"] == ""
    app = Workbench(root, root / "voices/voices.json")
    assert all(Path(v["audio"]).is_file() for v in app.voices())
