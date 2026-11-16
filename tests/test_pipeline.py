import unittest
from unittest.mock import Mock

import torch

from ghostline_audio.alignment import ctc_path
from ghostline_audio.batch import validate_manifest
from ghostline_audio.curves import synthesize
from ghostline_audio.voices import Sampling, VoiceEngine


class PipelineTests(unittest.TestCase):
    def test_ctc_repeated_phone_requires_blank(self):
        scores = torch.tensor([[.05, .95], [.99, .01], [.05, .95]]).log()
        runs = ctc_path(scores, [1, 1], 0)
        self.assertEqual([(r["start_frame"], r["end_frame"]) for r in runs], [(0, 1), (2, 3)])
        with self.assertRaises(ValueError):
            ctc_path(scores[:2], [1, 1], 0)

    def test_manifest_keeps_unsigned_64_bit_ids(self):
        manifest = {"voices": {"npc": {"reference_text": "Hello."}},
                    "lines": [{"id": str(2**64 - 1), "speaker": "npc", "text": "Hello."}]}
        validate_manifest(manifest)
        manifest["lines"].append(dict(manifest["lines"][0]))
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_base_instruction_is_separate_from_spoken_text(self):
        import numpy as np
        from unittest.mock import patch
        engine = VoiceEngine.__new__(VoiceEngine)
        engine.device = "cuda:0"
        engine.model = Mock()
        engine.model.generate_voice_clone.return_value = ([np.ones(2400)], 24000)
        with patch("torch.cuda.synchronize"), patch("torch.cuda.manual_seed_all"):
            engine.generate("Hello.", "English", "Speak quietly.", ["prompt"], Sampling(), 7)
        arguments = engine.model.generate_voice_clone.call_args.kwargs
        self.assertEqual(arguments["text"], "Hello.")
        self.assertEqual(arguments["instruct"], "Speak quietly.")
        self.assertEqual(arguments["voice_clone_prompt"], ["prompt"])

    def test_curves_exact_duration_and_neutral_ends(self):
        model = {"tracks": ["jaw"], "phase": [0, 1], "silence": {"median": [0]},
                 "phones": {"AA": {"curves": {"median": [[1], [1]]}}}}
        result = synthesize(model, {"duration": .333, "phones": [
            {"phone": "AA", "start": .05, "end": .25}]}, fps=30)
        self.assertEqual(result["times"][-1], .333)
        self.assertEqual(result["values"][0], [0])
        self.assertEqual(result["values"][-1], [0])
        self.assertGreater(max(row[0] for row in result["values"]), .9)


if __name__ == "__main__":
    unittest.main()
