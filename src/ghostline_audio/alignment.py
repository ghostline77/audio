"""CTC phone alignment without deprecated torchaudio forced_align APIs."""

from pathlib import Path
import re

import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly


def ctc_path(log_probs: torch.Tensor, tokens: list[int], blank: int) -> list[dict]:
    """Viterbi alignment, retaining separate runs for repeated target phones."""
    scores = log_probs.detach().float().cpu()
    if scores.ndim != 2 or not tokens or blank in tokens:
        raise ValueError("Require frame-by-vocabulary scores and nonblank target tokens")
    frames, vocabulary = scores.shape
    if not 0 <= blank < vocabulary or any(not 0 <= token < vocabulary for token in tokens):
        raise ValueError("Token outside acoustic vocabulary")
    minimum = len(tokens) + sum(a == b for a, b in zip(tokens, tokens[1:]))
    if frames < minimum:
        raise ValueError("Audio is too short to align the requested phone sequence")
    sequence = torch.tensor([blank] + [value for token in tokens for value in (token, blank)])
    count = len(sequence)
    previous = torch.full((count,), -torch.inf)
    previous[0] = scores[0, blank]
    previous[1] = scores[0, tokens[0]]
    back = torch.zeros((frames, count), dtype=torch.int8)
    skip = torch.zeros(count, dtype=torch.bool)
    skip[2:] = (sequence[2:] != blank) & (sequence[2:] != sequence[:-2])
    for frame in range(1, frames):
        one = torch.cat((torch.tensor([-torch.inf]), previous[:-1]))
        two = torch.cat((torch.full((2,), -torch.inf), previous[:-2]))
        two[~skip] = -torch.inf
        best, direction = torch.stack((previous, one, two)).max(dim=0)
        previous = best + scores[frame, sequence]
        back[frame] = direction.to(torch.int8)
    state = count - 1 if previous[-1] >= previous[-2] else count - 2
    if not torch.isfinite(previous[state]):
        raise ValueError("No valid CTC alignment")
    states = [0] * frames
    for frame in range(frames - 1, -1, -1):
        states[frame] = state
        if frame:
            state -= int(back[frame, state])
    result = []
    for index, token in enumerate(tokens):
        occupied = [frame for frame, value in enumerate(states) if value == 2 * index + 1]
        if not occupied:
            raise ValueError(f"Unaligned target phone {index}")
        start, end = occupied[0], occupied[-1] + 1
        result.append({"token": token, "start_frame": start, "end_frame": end,
                       "score": float(scores[start:end, token].exp().mean())})
    return result


def normalize_phone(value: str) -> str:
    return re.sub(r"[012]$", "", value.strip().upper()).replace("AO", "AA")


class PhoneAligner:
    def __init__(self, checkpoint: str = "mostafaashahin/wav2vec2-base-timit-phoneme-arpa-39-v2",
                 device: str = "cuda:0"):
        from transformers import AutoFeatureExtractor, AutoModelForCTC, AutoTokenizer
        from g2p_en import G2p

        self.device = device
        self.checkpoint = checkpoint
        self.extractor = AutoFeatureExtractor.from_pretrained(checkpoint)
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)
        self.model = AutoModelForCTC.from_pretrained(checkpoint).to(device).eval()
        self.phonemizer = G2p()
        self.vocabulary = {normalize_phone(phone): index
                           for phone, index in self.tokenizer.get_vocab().items()}

    @torch.inference_mode()
    def align(self, audio: Path, text: str) -> dict:
        waveform, sample_rate = sf.read(audio, dtype="float32", always_2d=True)
        waveform = waveform.mean(axis=1)
        duration = len(waveform) / sample_rate
        if not duration or not np.isfinite(waveform).all():
            raise ValueError("Empty or non-finite audio")
        from math import gcd
        rate = self.extractor.sampling_rate
        divisor = gcd(rate, sample_rate)
        samples = resample_poly(waveform, rate // divisor, sample_rate // divisor)
        phones = [normalize_phone(phone) for phone in self.phonemizer(text)
                  if re.fullmatch(r"[A-Z]+[012]?", phone)]
        missing = sorted(set(phones) - self.vocabulary.keys())
        if missing:
            raise ValueError(f"Phones absent from acoustic vocabulary: {missing}")
        inputs = self.extractor(samples, sampling_rate=rate, return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        logits = self.model(**inputs).logits[0].float().log_softmax(dim=-1)
        runs = ctc_path(logits, [self.vocabulary[phone] for phone in phones],
                        self.model.config.pad_token_id)
        step = duration / logits.shape[0]
        centres = [(row["start_frame"] + row["end_frame"]) * step / 2 for row in runs]
        aligned = []
        for index, (phone, run) in enumerate(zip(phones, runs)):
            token_start, token_end = run["start_frame"] * step, run["end_frame"] * step
            aligned.append({"phone": phone,
                            "start": token_start if index == 0 else (centres[index - 1] + centres[index]) / 2,
                            "end": token_end if index == len(runs) - 1 else (centres[index] + centres[index + 1]) / 2,
                            "token_start": token_start, "token_end": token_end, "score": run["score"]})
        return {"duration": duration, "text": text, "phones": aligned,
                "model": self.checkpoint, "device": self.device}
