# Ghostline audio

Create NPC voices, clone your cast, and review dialogue takes in a local web UI.

## Open the workbench

Use Python 3.12 or newer. Install a [PyTorch build for your GPU](https://pytorch.org/get-started/locally/), then:

```powershell
python -m pip install -e .
ghostline-audio serve
```

Open **http://127.0.0.1:8791/** from this repo.

1. **Models & setup:** download a Base model if one is not already available.
2. **Dialogue → New dialogue:** enter a name. The app creates the file; no manifest or schema setup is required. Use **Open dialogue** to continue, or **Import dialogue JSON** for existing authoring files.
3. **Write lines:** choose a reviewed voice and enter its words. Drafts, line keys, localization IDs and voice-library binding save automatically.
4. **Generate takes:** choose how many performances to try per line (two by default). The app shows the total and opens Review when the audio is ready.
5. **Review takes:** listen and choose a performance for each line. Choices save automatically. **Export selected lines** copies the WAVs and prepares a downloadable ZIP.

Generation freezes a copy of the dialogue so you can keep editing safely. Previous generations remain available in Review. Documents live in `dialogues/`, generations in `work/dialogues/`, and default WAV exports in `exports/`.

**File & localization details** contains the automatically assigned namespace, file location and a read-only JSON export. There are no Load, Save, Generate IDs or Apply source steps in the normal workflow. **Generation settings** holds the model and seed; the reviewed voice library is connected automatically.

For new NPCs, **Voice Design** creates a reference to listen to and save into the cast before writing dialogue.

To work on dialogue in a separate project, set the workspace to its directory:

```powershell
ghostline-audio serve --workspace PATH_TO_PROJECT --library voices/voices.json
```

UI paths are relative to the selected workspace. The library argument is a local
path relative to the command's working directory. GPU synthesis requires CUDA or
ROCm PyTorch.

## Build the browser UI

The Python package includes the compiled React, TypeScript and Tailwind workbench. After editing its sources, run `npm ci` and `npm run build` from `ui/`. Both the workbench and reference comparisons are served by `ghostline-audio serve`.

## Download checkpoints without the UI

Download complete official Hugging Face checkpoints, including tokenizer files:

```powershell
ghostline-audio download-model base --output models/Qwen3-TTS-12Hz-1.7B-Base
ghostline-audio download-model design --output models/Qwen3-TTS-12Hz-1.7B-VoiceDesign
# Optional smaller cloning model:
ghostline-audio download-model base-small --output models/Qwen3-TTS-12Hz-0.6B-Base
```

Sources: [1.7B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base), [1.7B VoiceDesign](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign), [0.6B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base).
Already downloaded? Enter the local folder in the UI, or start with `--models path/to/checkpoints/Qwen` to use an existing checkpoint directory. Speech synthesis uses the pinned `faster-qwen3-tts` dependency. Install the project dependencies together rather than substituting a different Qwen backend.

## Dialogue JSON

Supply a namespace and stable line keys; the tool generates the uint64 IDs.

```json
{
  "namespace": "my-series.q001",
  "voice_library": "../voices/voices.json",
  "lines": [
    {"key": "greeting", "speaker": "Judy", "text": "Ready when you are."}
  ]
}
```

Existing `id` values are preserved as decimal strings with the full unsigned 64-bit range. Keep namespace/key stable when editing text. Rendering writes `resolved-manifest.json`; downstream localization and scenes must use those same IDs.

The voice library contains one configured reference per character, with separate female and male V voices. Each reference includes its recording, exact transcript and cached conditioning tensors. Alternative references are catalogued in `voices/variants.json`.

See [CLI, reference formats & lipsync](docs/reference.md) for advanced workflows.

For native lipsync export, install the facial writer with `cargo install --locked --git https://github.com/ghostline77/ghostline-red --bin ghostline-facial`, or pass its executable to `--native-exporter`.
