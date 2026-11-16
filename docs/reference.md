# CLI & formats

Run commands from the audio repo. `ghostline-audio --help` lists all options.

## Design → clone

```powershell
ghostline-audio design --speaker Iris --checkpoint models/Qwen3-TTS-12Hz-1.7B-VoiceDesign --text "You have the cache. Good." --description "A calm low alto, measured and precise." --output work/iris.wav
# Listen before adopting. The exact transcript and recording hash are retained.
ghostline-audio adopt-design work/iris.wav --library voices/voices.json
ghostline-audio render examples/dialogue.json --checkpoint models/Qwen3-TTS-12Hz-1.7B-Base --output work/auditions
```

VoiceDesign creates an NPC reference. Base clones that recording for subsequent lines. V always uses reviewed clone references. Adoption replaces the exact same speaker name in the catalogue; prior audio is retained.

## IDs & manifests

`resolve input.json --output work/resolved.json` assigns IDs without loading a model. It uses the original tool's unsigned FNV-1a 64-bit algorithm over UTF-8 `namespace:key`, with zero mapped to one. Explicit IDs always win. Text edits, line reordering, speaker and delivery changes do not change generated identities. Changing namespace/key before saving changes them; after saving, the explicit ID remains authoritative. Duplicate ID/gender bindings are rejected.

Use exported IDs in quest-builder dialogue `string_id`, subtitle maps, VO maps and lipsync names. Audio does not rewrite those downstream resources.

Optional manifest settings: `seed`, `candidates`, `sampling`, and per-line `gender` (`shared`, `female`, `male`), `language`, `instruction`. Inline `voices` override library entries. Paths are relative to the containing manifest/library. See [inline references](../examples/voices.json).

## Library formats

`voices/voices.json` is the active cast. A voice has either `reference_audio` plus exact `reference_text`, or `full_reference` pointing to a saved prompt's `reference.json`. Both may include default `instruction`. A per-line instruction overrides it and remains separate from spoken text.

Older manifests should replace variant speaker names such as `Judy Reference 1 [original]` with the canonical name `Judy`. The complete imported catalogue remains in `voices/variants.json` for comparison.

Saved full references contain `reference.safetensors` (speaker embedding and codec tokens), `reference.wav`, and `reference.json` (transcript, dimensions, hashes). They load without re-encoding the recording. Designed voices use reviewed WAVs/transcripts, cached into full prompts on first render.

`import-library manifest.json --output work/imported-voices` imports legacy bundles. The manifest has a `references` array with `name`, `speaker`, `variant`, `embedding`, `codes`, `audio`, `reference_text`, and optional `instruction` and `selection`. Import to staging when auditing variants; explicitly select one per character for the active catalogue.

Codec JSON: `schema_version: 1`, `model: "qwen3_tts"`, `kind: "codec_frames"`, `layout: "frames_code_groups"`, dimensions `frame_count`/`code_groups`, flattened integer `values`. `merge-embeddings` averages same-speaker safetensors vectors.

## Review & promotion

The web UI records selected WAV hashes in `selections.csv`. CLI users can listen to `work/auditions/review.html` and mark CSV rows `yes`, then run:

```powershell
ghostline-audio promote --output work/auditions --selections work/auditions/selections.csv --destination ../my-series/quests/q001/voice/source
```

Promotion rejects changed WAVs and duplicate selections for one line/gender. Receipts identify weights, dependencies, seed, sampling, text, instruction and reference contents. Resume verifies request identity and WAV hash. Failures go in `report.json` and cause a nonzero exit.

## Lipsync

```powershell
ghostline-audio lipsync --audio work/reviewed-source/shared_0123456789ABCDEF.wav --text "Hello." --model models/lipsync/lipsync-templates.json --id 81985529216486895 --gender female --output work/line.curves.json
```

Alignment uses a public Wav2Vec2 ARPABET CTC model. Supply learned trajectory templates in `ghostline-lipsync-templates-v1` format; `g2p-en` needs its NLTK data. Output is named-track curve JSON.

`lipsync-batch manifest.json --model templates.json --output work/curves` processes
a `lines` array of `audio`, `text`, `id` and facial `gender` bindings. It loads the
models once and resumes unchanged outputs. Add `--animset quest/lipsync/dialogue.anims
--game GAME --rig DEPOT_PATH` to finish native export in the same
command. Audio invokes the shared native facial writer from `ghostline-red`; the
writer generates additive scalar tracks and verifies the resulting animation set.
`--native-exporter` overrides its executable. Wwise WEM encoding remains separate.

## Web server

`serve` (alias `ui`) binds to `127.0.0.1:8791`; `--port` overrides it. Mutations require a session token. File access is limited to `--workspace` and the library directory. One download/render/design/promotion job runs at a time. The server needs no model imports. Jobs use separate Python processes, releasing GPU memory when finished.
