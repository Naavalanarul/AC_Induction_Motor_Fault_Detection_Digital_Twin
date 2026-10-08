"""CLI: python -m app.validation.run --dataset <name> --protocol <name> [options]

Examples (from backend/):
    python -m app.validation.run --dataset sim --protocol sim_baseline
    python -m app.validation.run --dataset bruinsma --data-root ../data/validation/bruinsma --protocol zero_shot
    python -m app.validation.run --dataset liman_c --protocol all --seeds 0 1 2

If the dataset cannot be loaded (missing files, login-gated download, unexpected columns, unknown
licence-gated layout) the CLI exits with status 2 and a message; it never substitutes synthetic data.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.validation import table as T
from app.validation.loaders import LOADERS, DatasetUnavailable, LoaderOptions, get_loader
from app.validation.loaders.base import load_column_map
from app.validation.protocols import PROTOCOLS, Context

REPO_ROOT = Path(__file__).resolve().parents[3]
EXIT_DATASET_UNAVAILABLE = 2
SIM_ONLY = {"sim_baseline"}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m app.validation.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, choices=sorted(LOADERS) + ["sim"])
    ap.add_argument("--protocol", required=True, choices=sorted(PROTOCOLS) + ["all"])
    ap.add_argument("--data-root", type=Path, default=None,
                    help="dataset directory (default: <repo>/data/validation/<dataset>)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "reports" / "validation")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--model", choices=["rf", "logreg", "mlp"], default="rf")
    ap.add_argument("--sim-runs-per-class", type=int, default=20)
    ap.add_argument("--sim-seconds", type=float, default=4.0)
    ap.add_argument("--ks", type=int, nargs="+", default=[1, 2, 5, 10, 20])
    ap.add_argument("--max-records", type=int, default=None, help="cap recordings read (smoke runs; recorded in meta)")
    ap.add_argument("--manifest", type=Path, default=None, help="CSV overriding filename parsing (see docs)")
    ap.add_argument("--column-map", default=None, help="JSON (inline or file): canonical name -> column/field")
    ap.add_argument("--filename-regex", default=None, help="override the dataset's file-name pattern")
    ap.add_argument("--no-cache", action="store_true", help="do not read/write the feature cache")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    protocols = list(PROTOCOLS) if args.protocol == "all" else [args.protocol]
    if args.dataset == "sim":
        bad = [p for p in protocols if p not in SIM_ONLY]
        if args.protocol == "all":
            protocols = sorted(SIM_ONLY)
        elif bad:
            print(f"error: protocol {bad[0]} needs a real dataset; --dataset sim supports {sorted(SIM_ONLY)}",
                  file=sys.stderr)
            return 1

    cache_dir = None if args.no_cache else args.out / args.dataset / "_cache"
    ctx = Context(dataset=args.dataset, out_root=args.out, seeds=args.seeds, model_kind=args.model,
                  sim_runs_per_class=args.sim_runs_per_class, sim_seconds=args.sim_seconds, ks=tuple(args.ks),
                  cache_dir=cache_dir)
    if args.dataset != "sim":
        root = args.data_root or (REPO_ROOT / "data" / "validation" / args.dataset)
        try:
            opts = LoaderOptions(manifest=args.manifest, column_map=load_column_map(args.column_map),
                                 max_records=args.max_records, filename_regex=args.filename_regex)
            loader = get_loader(args.dataset, root, opts)
            ctx.loader = loader
            key = T.cache_key({"v": "real-v1", "root": str(root.resolve()), "opts": repr(opts)})
            path = cache_dir / f"real_{key}.npz" if cache_dir else None
            if path and path.exists():
                ctx.real = T.load(path)
            else:
                ctx.real = T.build(loader.iter_records())
                if path:
                    T.save(ctx.real, path)
        except DatasetUnavailable as exc:
            print(f"dataset unavailable: {exc}", file=sys.stderr)
            return EXIT_DATASET_UNAVAILABLE
        if not ctx.real.records:
            print("dataset unavailable: no usable recordings after pre-processing "
                  f"(skipped: {ctx.real.skipped[:3]})", file=sys.stderr)
            return EXIT_DATASET_UNAVAILABLE
        info = loader.info
        ctx.run_meta = {"dataset_title": info.title, "dataset_version": info.version, "dataset_source": info.source,
                        "licence": info.licence, "verified_format": list(info.verified),
                        "assumed_format": list(info.assumed), "data_root": str(root),
                        "max_records": args.max_records, "manifest": str(args.manifest) if args.manifest else None}
        print(f"{info.name}: {len(ctx.real.records)} recordings, classes "
              f"{sorted({r['label'] for r in ctx.real.records})}")
        for ch, status in T.channel_report(ctx.real).items():
            print(f"  channel {ch}: {status}")
        if not ctx.common_classes():
            print("dataset unavailable: no class in common with the twin's fault vocabulary", file=sys.stderr)
            return EXIT_DATASET_UNAVAILABLE
    else:
        ctx.run_meta = {"dataset_title": "simulator only", "dataset_version": "this commit"}

    for name in protocols:
        try:
            out = PROTOCOLS[name](ctx)
            print(f"-> {out}")
        except DatasetUnavailable as exc:
            print(f"dataset unavailable during {name}: {exc}", file=sys.stderr)
            return EXIT_DATASET_UNAVAILABLE
    return 0


if __name__ == "__main__":
    sys.exit(main())
