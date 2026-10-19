"""Command line interface for the BRMuniPanel ETL and dataset build tool."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

import brmunipanel
from brmunipanel.pipeline import SOURCES, run_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brmunipanel",
        description="BRMuniPanel command-line interface for municipal dataset ETL and packaging.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {brmunipanel.__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser(
        "build",
        help="Build the harmonized dataset from raw files.",
        description="Executes download, harmonization, consolidation, and packaging stages.",
    )
    build_parser.add_argument(
        "--raw-dir",
        required=True,
        help="Directory containing the raw input datasets.",
    )
    build_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where intermediate, processed, and final artifacts are written.",
    )
    build_parser.add_argument(
        "--sources",
        nargs="+",
        choices=list(SOURCES),
        default=list(SOURCES),
        help="Subset of sources to download or harmonize (default: all sources).",
    )
    build_parser.add_argument(
        "--stage",
        choices=["download", "harmonize", "consolidate", "finalize", "all"],
        default="all",
        help="Pipeline stage to execute (default: all).",
    )
    build_parser.add_argument(
        "--dataset-version",
        help="Dataset release version (required for finalize stage, e.g. 0.3.0).",
    )
    build_parser.add_argument(
        "--date",
        help="Dataset generation date (required for finalize stage, YYYY-MM-DD).",
    )
    build_parser.add_argument(
        "--license",
        dest="dataset_license",
        help="License identifier for the dataset deposit (e.g. CC-BY-4.0).",
    )
    build_parser.add_argument(
        "--doi",
        help="Digital Object Identifier (DOI) of the dataset deposit.",
    )
    build_parser.add_argument(
        "--url",
        help="Canonical URL of the dataset deposit repository.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        run_data(
            raw_dir=args.raw_dir,
            output_dir=args.output_dir,
            sources=args.sources,
            stage=args.stage,
            dataset_version=args.dataset_version,
            date=args.date,
            dataset_license=args.dataset_license,
            doi=args.doi,
            url=args.url,
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
