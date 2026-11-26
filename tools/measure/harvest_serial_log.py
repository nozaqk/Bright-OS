#!/usr/bin/env python3
"""Harvest a Bright OS measurement JSON block from a serial/QEMU log.

When `run-baseline.sh` runs inside a booted Bright OS QEMU instance, it
emits markers around the measurement JSON. The lines may carry a syslog
prefix (e.g. "[bright-measure]") when captured via the journal, or may
be plain when captured via direct serial console. This tool strips common
prefixes and extracts the first JSON document between BEGIN/END markers.

Markers we look for (case-sensitive, one per line):
    <anything> BRIGHT-OS-MEASUREMENT-JSON-BEGIN <anything>
    <JSON lines>
    <anything> BRIGHT-OS-MEASUREMENT-JSON-END <anything>

Returns exit code 0 if a valid measurement was found and written;
non-zero otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

BEGIN_TOKEN = "BRIGHT-OS-MEASUREMENT-JSON-BEGIN"
END_TOKEN = "BRIGHT-OS-MEASUREMENT-JSON-END"
# Common syslog/printk prefixes we strip from every line before looking
# for JSON structure:
#   "[bright-measure] "           our own SyslogIdentifier
#   "MMM DD HH:MM:SS host "      syslog timestamp (journal ForwardToConsole=yes)
#   "[  OK  ] " / "[FAILED] "    systemd status markers
#   "[   12.345678] "            printk timestamp
LINE_PREFIX_RE = re.compile(
    r"^("
    r"\[[\w\-]+\]\s*"                            # [bright-measure]
    r"|\[[ .]*OK[ .]*\]\s*"                       # [  OK  ]
    r"|\[\s*FAILED\s*\]\s*"                       # [FAILED]
    r"|\[\s*\d+\.\d+\]\s*"                        # [  12.345678]
    r"|[A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+\s+\S+\s+"  # Jan 01 00:00:00 host
    r")*"
)


def strip_prefixes(line: str) -> str:
    return LINE_PREFIX_RE.sub("", line, count=1)


def extract(log_text: str) -> dict | None:
    """Return the first measurement JSON document found in log_text, or None."""
    in_block = False
    buf_lines: list[str] = []
    for raw in log_text.splitlines():
        line = strip_prefixes(raw.rstrip("\r"))
        if BEGIN_TOKEN in line:
            in_block = True
            buf_lines = []
            continue
        if END_TOKEN in line:
            if in_block:
                blob = "\n".join(buf_lines).strip()
                try:
                    return json.loads(blob)
                except json.JSONDecodeError as e:
                    print(f"Found JSON markers but failed to parse: {e}", file=sys.stderr)
                    print(f"First 200 chars of block: {blob[:200]!r}", file=sys.stderr)
                    in_block = False
                    buf_lines = []
                    continue
            # else END seen without BEGIN; keep looking
        if in_block:
            buf_lines.append(line)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log", help="Path to serial log file")
    ap.add_argument("--out", "-o", required=True, help="Path to write extracted JSON")
    args = ap.parse_args()

    text = pathlib.Path(args.log).read_text(encoding="utf-8", errors="replace")
    doc = extract(text)
    if doc is None:
        print(f"No measurement block found in {args.log}", file=sys.stderr)
        return 1
    pathlib.Path(args.out).write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    s = doc.get("summary", {})
    print(f"Extracted measurement: {json.dumps(s)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
