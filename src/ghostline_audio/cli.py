"""Standalone voice and lipsync authoring commands."""

import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ghostline-audio")
    commands = parser.add_subparsers(dest="command", required=True)
    ui = commands.add_parser("serve", aliases=["ui"], help="Serve the local web audio workbench")
    ui.add_argument("--library", type=Path, default=Path("voices/voices.json"))
    ui.add_argument("--workspace", type=Path, default=Path.cwd())
    ui.add_argument("--port", type=int, default=8791)
    ui.add_argument("--models", type=Path, help="Existing checkpoint directory (default: workspace/models)")
    download = commands.add_parser("download-model", help="Download a complete official Qwen checkpoint")
    download.add_argument("model", choices=["base", "design", "base-small"])
    download.add_argument("--output", type=Path, required=True)
    resolve = commands.add_parser("resolve", help="Assign stable IDs without loading a speech model")
    resolve.add_argument("manifest", type=Path)
    resolve.add_argument("--output", type=Path, required=True)
    adopt = commands.add_parser("adopt-design", help="Save a reviewed design as the NPC's library voice")
    adopt.add_argument("audio", type=Path)
    adopt.add_argument("--library", type=Path, default=Path("voices/voices.json"))
    reference = commands.add_parser("import-library", help="Package saved full references without running a model")
    reference.add_argument("manifest", type=Path)
    reference.add_argument("--output", required=True, type=Path)
    reference.add_argument("--report", type=Path)
    render = commands.add_parser("render", help="Generate resumable voice auditions")
    render.add_argument("manifest", type=Path)
    render.add_argument("--checkpoint", required=True)
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--device", default="cuda:0")
    select = commands.add_parser("promote", help="Copy explicitly reviewed takes to source WAVs")
    select.add_argument("--output", required=True, type=Path)
    select.add_argument("--selections", required=True, type=Path)
    select.add_argument("--destination", required=True, type=Path)
    merge = commands.add_parser("merge-embeddings", help="Average same-speaker safetensors embeddings")
    merge.add_argument("inputs", nargs="+", type=Path)
    merge.add_argument("--output", required=True, type=Path)
    design = commands.add_parser("design", help="Produce a new NPC voice reference")
    design.add_argument("--speaker", required=True)
    design.add_argument("--checkpoint", required=True)
    design.add_argument("--text", required=True)
    design.add_argument("--description", required=True)
    design.add_argument("--language", default="English")
    design.add_argument("--seed", type=int, default=0)
    design.add_argument("--output", type=Path, required=True)
    design.add_argument("--device", default="cuda:0")
    lipsync = commands.add_parser("lipsync", help="Align a WAV and synthesize learned facial curves")
    lipsync.add_argument("--audio", required=True, type=Path)
    lipsync.add_argument("--text", required=True)
    lipsync.add_argument("--model", required=True, type=Path)
    lipsync.add_argument("--output", required=True, type=Path)
    lipsync.add_argument("--id", type=int, required=True)
    lipsync.add_argument("--gender", choices=["female", "male"], required=True)
    lipsync.add_argument("--fps", type=float, default=30)
    lipsync.add_argument("--device", default="cuda:0")
    lipsync_batch = commands.add_parser("lipsync-batch", help="Generate facial curves for a WAV manifest with one resident model")
    lipsync_batch.add_argument("manifest", type=Path)
    lipsync_batch.add_argument("--model", required=True, type=Path)
    lipsync_batch.add_argument("--output", required=True, type=Path)
    lipsync_batch.add_argument("--device", default="cuda:0")
    lipsync_batch.add_argument("--animset", type=Path, help="Also write the native .anims resource")
    lipsync_batch.add_argument("--game", type=Path)
    lipsync_batch.add_argument("--schema", type=Path)
    lipsync_batch.add_argument("--rig", help="Native facial rig depot path")
    lipsync_batch.add_argument("--native-exporter", type=Path)
    args = parser.parse_args(argv)
    if args.command in {"serve", "ui"}:
        from .server import serve
        serve(args.workspace, args.library, args.port, args.models)
    elif args.command == "download-model":
        from .models import download_model
        download_model(args.model, args.output)
    elif args.command == "resolve":
        from .manifests import assign_ids
        from .files import read_json, write_json
        result = assign_ids(read_json(args.manifest))
        # Relocation must not change the meaning of relative input paths.
        from .files import local_path
        if result.get("voice_library"):
            result["voice_library"] = str(local_path(args.manifest.parent, result["voice_library"]))
        for voice in result.get("voices", {}).values():
            for field in ("reference_audio", "full_reference", "embedding", "reference_codes"):
                if voice.get(field):
                    voice[field] = str(local_path(args.manifest.parent, voice[field]))
        write_json(args.output, result)
    elif args.command == "adopt-design":
        from .design import adopt_reference
        adopt_reference(args.audio, args.library)
    elif args.command == "import-library":
        from .references import import_library
        import_library(args.manifest, args.output, args.report)
    elif args.command == "render":
        from .batch import render_manifest
        render_manifest(args.manifest, args.output, args.checkpoint, args.device)
    elif args.command == "promote":
        from .batch import promote
        promote(args.output, args.selections, args.destination)
    elif args.command == "merge-embeddings":
        from .voices import merge_embeddings
        merge_embeddings(args.inputs, args.output)
    elif args.command == "design":
        from .design import design_reference
        design_reference(args.checkpoint, args.output, args.speaker, args.text,
                         args.description, args.language, args.seed, args.device)
    elif args.command == "lipsync-batch":
        from .lipsync_batch import export_native, generate_batch
        if args.animset and not all((args.game, args.rig)):
            parser.error("--animset requires --game and --rig")
        generate_batch(args.manifest, args.model, args.output, args.device)
        if args.animset:
            export_native(args.output, args.animset, args.game, args.schema, args.rig,
                          args.native_exporter)
    elif args.command == "lipsync":
        from .alignment import PhoneAligner
        from .curves import synthesize
        from .files import digest, read_json, write_json
        if not 0 < args.id < 2**64:
            parser.error("--id must be a nonzero uint64 localization ID")
        alignment = PhoneAligner(device=args.device).align(args.audio, args.text)
        curves = synthesize(read_json(args.model), alignment, fps=args.fps, device=args.device)
        write_json(args.output, {"schema": "ghostline-facial-curves-v1",
                   "name": f"{args.gender[0]}_{args.id:016X}", "locstring": str(args.id),
                   "audio_sha256": digest(args.audio), "model_sha256": digest(args.model),
                   "alignment": alignment, **curves})
    return 0
