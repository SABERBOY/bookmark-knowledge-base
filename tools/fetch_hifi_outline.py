#!/usr/bin/env python3
"""Outline for bulk hi-fi bookmark fetch (HTML primary, MD secondary).

Not wired into production yet — pilot only.
Chunk3 / old trafilatura pipeline should finish or pause separately.
"""
from __future__ import annotations

import json
import subprocess
import sqlite3
from pathlib import Path

ROOT = Path("/workspace/bookmark-db-hi-fi")  # or bookmark-db after cutover
HI = ROOT / "content_html"
MD = ROOT / "content_md"
SF = ROOT / "node_modules/.bin/single-file"
CHROME = "/usr/bin/google-chrome-stable"
DB = Path("/workspace/bookmark-db/bookmarks.sqlite")

BROWSER_ARGS = json.dumps(
    ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
)


def single_file(url: str, out_html: Path) -> bool:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(SF),
        url,
        str(out_html),
        "--browser-executable-path",
        CHROME,
        "--browser-args",
        BROWSER_ARGS,
        "--browser-load-max-time",
        "90000",
        "--browser-capture-max-time",
        "90000",
        "--browser-wait-until",
        "networkIdle",
        # size guards for bulk (tune after more pilots):
        # "--max-resource-size-enabled", "true",
        # "--max-resource-size", "2",  # MiB per resource
    ]
    try:
        subprocess.run(cmd, check=True, timeout=180)
        return out_html.exists() and out_html.stat().st_size > 2000
    except Exception as e:
        print("single-file fail", url, e)
        return False


def html_to_md(html_path: Path, md_path: Path, max_chars: int = 64000) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["markitdown", str(html_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = r.stdout or ""
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n…[truncated for index]…\n"
    md_path.write_text(text, encoding="utf-8")


def fetch_one(page_id: int, url: str) -> dict:
    html_path = HI / f"{page_id}.html"
    md_path = MD / f"{page_id}.md"
    ok = single_file(url, html_path)
    status = "ok" if ok else "fail"
    if ok:
        html_to_md(html_path, md_path)
    return {
        "id": page_id,
        "url": url,
        "status": status,
        "html_bytes": html_path.stat().st_size if html_path.exists() else 0,
        "md_bytes": md_path.stat().st_size if md_path.exists() else 0,
        "html_path": str(html_path.relative_to(ROOT)) if ok else None,
        "md_path": str(md_path.relative_to(ROOT)) if ok else None,
    }


def sketch_index_change():
    """UI rule: prefer .html; fall back to .md."""
    return """
// in index.html loadContent(id):
//   1) try fetch(`content_html/${id}.html`) → iframe/srcdoc or object
//   2) else fetch(`content_md/${id}.md`) → marked()
//   3) show badge: HTML原页 | 纯文本MD
"""


if __name__ == "__main__":
    print("Outline only. Example:")
    print(sketch_index_change())
    # Demo one id if run manually:
    # print(fetch_one(3, "https://www.redblobgames.com/articles/visibility/"))
