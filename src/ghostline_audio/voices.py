"""Public Qwen3-TTS Torch backend, including Base instruction conditioning."""

from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
import time

import numpy as np
import soundfile as sf
import torch
from safetensors.torch import load_file, save_file

from .files import digest, identity, read_json, write_json


@dataclass(frozen=True)
class Sampling:
    max_new_tokens: int = 1024
    min_new_tokens: int = 2
    temperature: float = 0.9
    top_k: int = 50
    top_p: float = 1.0
    do_sample: bool = True
    repetition_penalty: float = 1.05

    def __post_init__(self):
        if not 0 < self.min_new_tokens <= self.max_new_tokens:
            raise ValueError("Require 0 < min_new_tokens <= max_new_tokens")
        if self.temperature <= 0 or self.top_k < 0 or not 0 < self.top_p <= 1:
            raise ValueError("Invalid sampling settings")


def checkpoint_identity(checkpoint: str) -> dict:
    """Hash local weights once per backend, not once per dialogue line."""
    path = Path(checkpoint)
    if not path.is_dir():
        raise ValueError("Use a local downloaded checkpoint so receipts identify exact weights")
    files = sorted(p for p in path.rglob("*") if p.is_file() and
                   p.suffix in {".json", ".safetensors", ".model", ".txt"})
    if not files:
        raise ValueError(f"No model files in {path}")
    return {"path": str(path.resolve()), "sha256": identity(
        {p.relative_to(path).as_posix(): digest(p) for p in files})}


class VoiceEngine:
    """One resident model and a reusable full-reference prompt per voice."""

    def __init__(self, checkpoint: str, cache: Path, device: str = "cuda:0",
                 max_seq_len: int = 4096):
        if not torch.cuda.is_available() or not device.startswith("cuda"):
            raise RuntimeError("The fast Torch backend requires a CUDA/ROCm GPU")
        from faster_qwen3_tts import FasterQwen3TTS

        self.cache = cache
        self.provenance = {"checkpoint": checkpoint_identity(checkpoint),
                           "backend": "faster-qwen3-tts/torch",
                           "versions": {name: version(name) for name in
                                        ("faster-qwen3-tts", "qwen-tts-hf", "transformers", "torch")},
                           "device": torch.cuda.get_device_name(device),
                           "hip": torch.version.hip, "dtype": "bfloat16",
                           "attention": "sdpa", "max_seq_len": max_seq_len}
        self.device = device
        self.model = FasterQwen3TTS.from_pretrained(
            checkpoint, backend="torch", device=device, dtype=torch.bfloat16,
            attn_implementation="sdpa", max_seq_len=max_seq_len)
        self.prompts = {}

    def reference(self, audio: Path, text: str, embedding: Path | None = None):
        if not text.strip():
            raise ValueError("Full-reference cloning requires the exact reference transcript")
        key = identity({"audio": digest(audio), "text": text,
                        "speaker_embedding": digest(embedding) if embedding else None,
                        "model": self.provenance["checkpoint"]})
        if key not in self.prompts:
            tensors = self.cache / f"{key}.safetensors"
            metadata = self.cache / f"{key}.json"
            if tensors.exists() and metadata.exists() and read_json(metadata).get("sha256") == digest(tensors):
                from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem
                stored = load_file(str(tensors))
                prompt = [VoiceClonePromptItem(
                    ref_code=stored["ref_code"],
                    ref_spk_embedding=stored["speaker_embedding"],
                    x_vector_only_mode=False, icl_mode=True, ref_text=text)]
            else:
                prompt = self.model.model.create_voice_clone_prompt(
                    ref_audio=str(audio), ref_text=text, x_vector_only_mode=False)
                item = prompt[0]
                if embedding is not None:
                    vector = load_embedding(embedding)
                    if vector.shape != item.ref_spk_embedding.shape or not torch.isfinite(vector).all():
                        raise ValueError(f"Invalid speaker embedding: {embedding}")
                    item.ref_spk_embedding = vector.to(item.ref_spk_embedding)
                self.cache.mkdir(parents=True, exist_ok=True)
                save_file({"speaker_embedding": item.ref_spk_embedding.detach().cpu().contiguous(),
                           "ref_code": item.ref_code.detach().cpu().contiguous()}, str(tensors))
                write_json(metadata, {"key": key, "sha256": digest(tensors),
                                      "reference_audio_sha256": digest(audio), "reference_text": text})
            self.prompts[key] = prompt
        return self.prompts[key], key

    def saved_reference(self, path: Path):
        metadata = read_json(path)
        if metadata.get("schema") != "ghostline-voice-reference-v1" or metadata.get("mode") != "full_reference":
            raise ValueError(f"Not a saved full-reference bundle: {path}")
        if not metadata["reference_text"].strip():
            raise ValueError(f"Reference transcript is empty: {path}")
        tensor_path = path.parent / metadata["tensors"]
        if digest(tensor_path) != metadata["sha256"][metadata["tensors"]]:
            raise ValueError(f"Saved full-reference tensors changed: {tensor_path}")
        key = identity({"full_reference_tensors": metadata["sha256"][metadata["tensors"]],
                        "reference_text": metadata["reference_text"]})
        if key not in self.prompts:
            from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem
            tensors = load_file(str(tensor_path))
            codes, vector = tensors["ref_code"], tensors["speaker_embedding"]
            if (codes.shape != (metadata["frame_count"], metadata["code_groups"])
                    or codes.dtype != torch.int64 or torch.any(codes < 0)
                    or vector.ndim != 1 or not torch.isfinite(vector).all()):
                raise ValueError(f"Invalid full-reference tensors: {tensor_path}")
            self.prompts[key] = [VoiceClonePromptItem(
                ref_code=codes, ref_spk_embedding=vector,
                x_vector_only_mode=False, icl_mode=True, ref_text=metadata["reference_text"])]
        return self.prompts[key], key, metadata.get("instruction") or ""

    def generate(self, text: str, language: str, instruction: str,
                 prompt, sampling: Sampling, seed: int):
        if not text.strip():
            raise ValueError("Spoken text is empty")
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        started = time.perf_counter()
        # Deliberately separate from text: this is a conditioning user turn.
        audio, rate = self.model.generate_voice_clone(
            text=text, language=language, instruct=instruction or None,
            voice_clone_prompt=prompt, append_silence=False, **asdict(sampling))
        torch.cuda.synchronize(self.device)
        waveform = np.asarray(audio[0], dtype=np.float32).reshape(-1)
        if waveform.size < rate // 20 or not np.isfinite(waveform).all():
            raise RuntimeError("Generation returned empty, too short, or non-finite audio")
        elapsed = time.perf_counter() - started
        return waveform, rate, {"seconds": elapsed, "audio_seconds": len(waveform) / rate,
                                "realtime_factor": elapsed / (len(waveform) / rate)}

    def design(self, text: str, language: str, description: str, sampling: Sampling, seed: int):
        if not text.strip() or not description.strip():
            raise ValueError("Voice design requires reference text and a voice description")
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        audio, rate = self.model.generate_voice_design(text=text, language=language,
                                                       instruct=description, **asdict(sampling))
        waveform = np.asarray(audio[0], dtype=np.float32).reshape(-1)
        if waveform.size < rate // 20 or not np.isfinite(waveform).all():
            raise RuntimeError("Voice design returned empty, too short, or non-finite audio")
        return [waveform], rate


def load_embedding(path: Path) -> torch.Tensor:
    tensors = load_file(str(path))
    if "speaker_embedding" in tensors:
        vector = tensors["speaker_embedding"]
    elif "embedding" in tensors:
        vector = tensors["embedding"]
    else:
        raise ValueError(f"No speaker embedding in {path}")
    if vector.ndim != 1 or not torch.isfinite(vector).all():
        raise ValueError(f"Speaker embedding must be a finite vector: {path}")
    return vector


def merge_embeddings(inputs: list[Path], output: Path) -> None:
    if not inputs:
        raise ValueError("At least one same-speaker embedding is required")
    vectors = [load_embedding(path).float() for path in inputs]
    if any(vector.shape != vectors[0].shape for vector in vectors):
        raise ValueError("Embedding dimensions differ")
    merged = torch.stack(vectors).mean(dim=0)
    if not torch.isfinite(merged).all():
        raise ValueError("Non-finite speaker embedding")
    output.parent.mkdir(parents=True, exist_ok=True)
    save_file({"speaker_embedding": merged.contiguous()}, str(output))
    write_json(output.with_suffix(".json"), {"operation": "same-speaker arithmetic mean",
               "inputs": [{"path": str(p), "sha256": digest(p)} for p in inputs],
               "sha256": digest(output)})


def write_audio(path: Path, audio, sample_rate: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".writing.wav")
    sf.write(temporary, audio, sample_rate, subtype="PCM_16")
    temporary.replace(path)
