#!/usr/bin/env python3
"""Build hifi-ids.json (+ optional report) from SingleFile HTML directory.

Excludes files larger than Cloudflare Workers static asset limit (25 MiB).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LIMIT = 25 * 1024 * 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--html-dir",
        type=Path,
        default=Path("/workspace/bookmark-db-hi-fi/content_html"),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("/workspace/bookmark-site/preview/hifi-ids.json"),
    )
    ap.add_argument("--report", type=Path, default=None, help="Write oversized list JSON")
    ap.add_argument("--copy-to", type=Path, default=None, help="Copy under-limit HTML here")
    args = ap.parse_args()

    if not args.html_dir.is_dir():
        print(f"missing html dir: {args.html_dir}", file=sys.stderr)
        return 1

    ok_ids: list[int] = []
    oversized: list[dict] = []
    total_ok = 0
    for p in sorted(args.html_dir.glob("*.html"), key=lambda x: int(x.stem) if x.stem.isdigit() else 10**12):
        if not p.stem.isdigit():
            continue
        sz = p.stat().st_size
        id_ = int(p.stem)
        if sz > LIMIT:
            oversized.append({"id": id_, "file": p.name, "bytes": sz, "mib": round(sz / 1024 / 1024, 2)})
            continue
        ok_ids.append(id_)
        total_ok += sz
        if args.copy_to:
            args.copy_to.mkdir(parents=True, exist_ok=True)
            dest = args.copy_to / p.name
            dest.write_bytes(p.read_bytes())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(ok_ids))
    report = {
        "limit_bytes": LIMIT,
        "included": len(ok_ids),
        "excluded_oversized": len(oversized),
        "included_bytes": total_ok,
        "included_mib": round(total_ok / 1024 / 1024, 2),
        "oversized": oversized,
        "ids_out": str(args.out),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ("included", "excluded_oversized", "included_mib")}, ensure_ascii=False))
    if oversized:
        print("oversized:", ", ".join(f"{o['file']}({o['mib']}MiB)" for o in oversized))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
