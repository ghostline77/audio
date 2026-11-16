"""Official checkpoint catalogue and complete, resumable Hub downloads."""

MODELS = {
    "base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "base-small": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
}


def download_model(model, output):
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=MODELS[model], local_dir=str(output))


def model_path(directory, model):
    return directory / MODELS[model].split("/")[1]
