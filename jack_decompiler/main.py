"""
main.py - The command line: `jackdecomp` / `python -m jack_decompiler`.
======================================================================

    jackdecomp                          open the GUI (choose a program there)
    jackdecomp games/pong               open the GUI showing games/pong
    jackdecomp games/pong -o out        write out/*.jack (no window)
    jackdecomp Main.vm --stdout         print the Jack code
    jackdecomp games/pong --verify      recompile and compare with the VM

Exit codes: 0 = fine, 1 = some subroutines couldn't be decompiled or the
check found a difference, 2 = bad input (missing files, VM syntax errors).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .decompiler import decompile_files
from .output import save_result
from .verify import verify
from .vm_reader import VMSyntaxError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jackdecomp",
        description="Decompile nand2tetris Jack VM code (.vm) back into Jack source (.jack).",
        epilog="With no -o/--stdout/--verify, the GUI opens (Ctrl+Q quits, Ctrl+O opens another program).",
    )
    parser.add_argument("paths", nargs="*", help=".vm files and/or folders of .vm files (one program)")
    parser.add_argument("-o", "--out", metavar="FOLDER", help="write one .jack file per class into FOLDER")
    parser.add_argument("--stdout", action="store_true", help="print the decompiled Jack code")
    parser.add_argument("--verify", action="store_true",
                        help="recompile the Jack code and check it gives the same VM code")
    parser.add_argument("--force", action="store_true", help="with -o: overwrite existing .jack files")
    parser.add_argument("--keep-function-names", action="store_true",
                        help="don't rename meaningless function names such as f1 or func_2")
    parser.add_argument("--gui", action="store_true", help="open the GUI even with -o/--stdout/--verify")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    headless = args.out or args.stdout or args.verify
    if not headless or args.gui:
        if args.force and not args.out:
            print("note: --force only matters together with -o", file=sys.stderr)
        from .gui.app import run_gui  # pygame is only needed for the GUI

        return run_gui([Path(p) for p in args.paths], rename_functions=not args.keep_function_names)
    if not args.paths:
        print("jackdecomp: give at least one .vm file or folder (or no options at all for the GUI)", file=sys.stderr)
        return 2

    try:
        result = decompile_files([Path(p) for p in args.paths], rename_functions=not args.keep_function_names)
    except (FileNotFoundError, VMSyntaxError) as error:
        print(f"jackdecomp: {error}", file=sys.stderr)
        return 2

    status = 0
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"error: couldn't decompile {error}", file=sys.stderr)
        status = 1
    if args.stdout:
        print("\n".join(c.jack for c in result.classes.values()), end="")
    if args.out:
        try:
            written = save_result(result, Path(args.out), force=args.force)
        except (FileExistsError, OSError) as error:
            print(f"jackdecomp: {error}", file=sys.stderr)
            return 2
        print(f"Wrote {len(written)} file{'s' if len(written) != 1 else ''} to {Path(args.out)}", file=sys.stderr)
    if args.verify:
        for check in verify(result):
            print(f"{'OK  ' if check.ok else 'DIFF'} {check.name}: {check.message}", file=sys.stderr)
            if not check.ok:
                status = 1
    print(f"Decompiled {result.summary()}", file=sys.stderr)
    return status


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
