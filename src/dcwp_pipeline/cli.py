"""Command-line entry point.

    dcwp-pipeline run                  # full pipeline
    dcwp-pipeline extract              # refresh the cached extract only
    dcwp-pipeline run --cached         # skip the API, use the cache
    dcwp-pipeline run --max-rows 5000  # quick smoke run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dcwp-pipeline",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["run", "extract", "validate", "analyse"])
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "pipeline.json")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--cached", action="store_true", help="use cached extract, skip the API")
    parser.add_argument("--max-rows", type=int, default=None, help="cap rows per source")
    parser.add_argument(
        "--ignore-quality-failures",
        action="store_true",
        help="continue past error-severity quality failures (not recommended)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    config = pipeline.load_config(args.config)
    paths = pipeline.Paths(root=args.root)
    paths.ensure()

    if args.command == "extract":
        pipeline.extract(config, paths, max_rows=args.max_rows)
        return 0

    frames = (
        pipeline.load_cached(config, paths)
        if args.cached
        else pipeline.extract(config, paths, max_rows=args.max_rows)
    )

    report = pipeline.validate(frames, config, paths, sampled=args.max_rows is not None)
    if args.command == "validate":
        return 0 if report.ok else 1

    if not report.ok and not args.ignore_quality_failures:
        logging.error(
            "Refusing to publish analysis on data that failed %d error-severity "
            "check(s). See reports/data_quality.md. Override with "
            "--ignore-quality-failures if you understand why.",
            len(report.errors),
        )
        return 1

    models = pipeline.build_models(frames)
    pipeline.write_warehouse(models, paths)
    pipeline.analyse(models, config, paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
