#!/usr/bin/env python3
"""Syntax-check a Python source file without writing bytecode to the source tree.

Used by the shell test suites so they can run as a non-root user (e.g.
'nobody') against a read-only checkout. Usage:

    python3 tests/support/py_syntax_check.py <file> [<file> ...]

Exit codes:
    0  all files compiled cleanly
    1  at least one file has a syntax error
    2  at least one file could not be opened (missing, permission denied, etc.)
"""
import os
import py_compile
import sys
import tempfile


def check_file(path: str) -> int:
    """Compile `path` to a temporary .pyc; return 0 on success, 1 on syntax
    error, 2 on I/O failure."""
    if not os.path.isfile(path):
        print(f"py_syntax_check: not a file: {path}", file=sys.stderr)
        return 2
    fd, cfile = tempfile.mkstemp(prefix="bright-pyc-", suffix=".pyc")
    os.close(fd)
    try:
        py_compile.compile(path, cfile=cfile, doraise=True)
        return 0
    except py_compile.PyCompileError as e:
        print(f"py_syntax_check: syntax error in {path}: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"py_syntax_check: could not read {path}: {e}", file=sys.stderr)
        return 2
    finally:
        try:
            os.unlink(cfile)
        except OSError:
            pass


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    worst = 0
    for path in argv:
        rc = check_file(path)
        if rc > worst:
            worst = rc
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
