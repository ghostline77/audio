"""Learned game facial trajectories, vectorized over frames using PyTorch."""

import math

import torch


def synthesize(model: dict, alignment: dict, fps: float = 30, device: str = "cpu",
               context_weight: float = 0.7, fallback_ms: float = 60,
               maximum_ms: float = 120, zero_prefixes: tuple[str, ...] = ()) -> dict:
    duration = float(alignment["duration"])
    if not all(math.isfinite(value) and value > 0 for value in (duration, fps)):
        raise ValueError("Duration and fps must be finite and positive")
    if any(not math.isfinite(value) or value < 0
           for value in (context_weight, fallback_ms, maximum_ms)):
        raise ValueError("Transition and context settings must be finite and nonnegative")
    tracks = model["tracks"]
    if not tracks or len(set(tracks)) != len(tracks):
        raise ValueError("Curve model must have unique track names")
    times = torch.arange(math.ceil(duration * fps), device=device, dtype=torch.float64) / fps
    times = torch.cat((times[times < duration - 1e-6], times.new_tensor([duration])))
    phase = torch.tensor(model["phase"], device=device, dtype=torch.float64)
    if phase.ndim != 1 or len(phase) < 2 or not torch.all(phase[1:] > phase[:-1]):
        raise ValueError("Model phase grid must be strictly increasing")
    silence = torch.tensor(model["silence"]["median"], device=device, dtype=torch.float64)
    if silence.shape != (len(tracks),):
        raise ValueError("Silence pose does not match track count")
    weighted = torch.zeros((len(times), len(tracks)), device=device, dtype=torch.float64)
    weights = torch.zeros(len(times), device=device, dtype=torch.float64)
    contexts = {direction: {(row["phone"], row["context_phone"]): row["delta_median"]
                           for row in model.get("contexts", {}).get(direction, [])}
                for direction in ("previous", "next")}

    def interpolate(values, query):
        values = torch.tensor(values, device=device, dtype=torch.float64)
        if values.shape != (len(phase), len(tracks)) or not torch.isfinite(values).all():
            raise ValueError("Invalid learned trajectory shape or values")
        query = query.clamp(phase[0], phase[-1])
        lower = (torch.searchsorted(phase, query, right=True) - 1).clamp(0, len(phase) - 2)
        fraction = ((query - phase[lower]) / (phase[lower + 1] - phase[lower])).unsqueeze(1)
        return values[lower] * (1 - fraction) + values[lower + 1] * fraction

    def transition(boundary, name):
        value = boundary.get(f"{name}_ms")
        if value is None or boundary.get(f"{name}_censored", False):
            value = fallback_ms
        return min(abs(float(value)), maximum_ms) / 1000

    def smooth(value):
        value = value.clamp(0, 1)
        return value * value * (3 - 2 * value)

    phones = alignment["phones"]
    if not phones:
        raise ValueError("Cannot synthesize lipsync without aligned phones")
    for index, item in enumerate(phones):
        phone = item["phone"]
        if phone not in model["phones"]:
            raise ValueError(f"Curve model has no trajectory for {phone}")
        start, end = float(item["start"]), float(item["end"])
        if not 0 <= start < end <= duration:
            raise ValueError(f"Invalid phone interval: {item}")
        boundary = model.get("boundaries", {}).get(phone, {})
        anticipation = transition(boundary, "anticipation")
        release = transition(boundary, "release")
        weight = torch.where(times < start,
                             smooth((times - start + anticipation) / max(anticipation, 1e-6)),
                             torch.where(times > end,
                                         1 - smooth((times - end) / max(release, 1e-6)), 1))
        query = (times - start) / max(end - start, 1e-6)
        pose = interpolate(model["phones"][phone]["curves"]["median"], query)
        previous = phones[index - 1]["phone"] if index else "SIL"
        following = phones[index + 1]["phone"] if index + 1 < len(phones) else "SIL"
        for direction, neighbour in (("previous", previous), ("next", following)):
            delta = contexts[direction].get((phone, neighbour))
            if delta is not None:
                pose += context_weight * interpolate(delta, query)
        weighted += pose * weight[:, None]
        weights += weight
    prediction = (weighted + (1 - weights).clamp_min(0)[:, None] * silence) / weights.clamp_min(1)[:, None]
    first, last = phones[0]["start"], phones[-1]["end"]
    gate = ((times - (first - .08)) / .08).clamp(0, 1)
    gate *= (((last + .08) - times) / .08).clamp(0, 1)
    prediction *= gate[:, None]
    prediction[0] = 0
    prediction[-1] = 0
    for index, track in enumerate(tracks):
        if track.startswith(zero_prefixes):
            prediction[:, index] = 0
    if not torch.isfinite(prediction).all():
        raise ValueError("Synthesis produced non-finite values")
    return {"duration": duration, "fps": fps, "tracks": tracks,
            "times": times.cpu().tolist(), "values": prediction.cpu().tolist(),
            "settings": {"context_weight": context_weight, "fallback_transition_ms": fallback_ms,
                         "maximum_transition_ms": maximum_ms, "zero_prefixes": zero_prefixes}}
