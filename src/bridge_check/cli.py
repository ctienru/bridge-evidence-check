"""Command-line entry point: `bridge`."""

from __future__ import annotations

import argparse
import sys

from bridge_check import __version__

EXIT_OK = 0
EXIT_FAILED = 3

_STUB_COMMANDS = {
    "check": "Check one case and print evidence statuses.",
    "eval": "Evaluate a split against frozen gold.",
    "excerpts": "Run the excerpt tests.",
    "history": "Show past runs for one case.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bridge",
        description="Medicare GLP-1 Bridge pre-attestation chart evidence checker.",
    )
    parser.add_argument("--version", action="version", version=f"bridge {__version__}")
    sub = parser.add_subparsers(dest="command")
    for name, help_text in _STUB_COMMANDS.items():
        sub.add_parser(name, help=help_text)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits for --version / --help / bad args
        return int(exc.code) if isinstance(exc.code, int) else EXIT_OK
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    print(f"bridge {args.command}: not implemented yet", file=sys.stderr)
    return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
