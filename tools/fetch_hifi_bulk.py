#!/usr/bin/env python3
"""Bulk hi-fi bookmark fetch: SingleFile HTML primary, markitdown MD secondary.

Resumable via SQLite progress DB. Reuses skip rules from bookmark-db/tools/fetch_chunk.py.
Monolith only as fallback when SingleFile fails AND HTTP returns a real body.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import ssl
import urllib.error

# Reuse skip helpers from old pipeline
sys.path.insert(0, "/workspace/bookmark-db/tools")
from fetch_chunk import (  # noqa: E402
    should_skip_before_fetch,
    host_of,
)

ROOT = Path("/workspace/bookmark-db-hi-fi")
CSV_PATH = Path("/workspace/bookmarks_merged.csv")
HI = ROOT / "content_html"
MD = ROOT / "content_md"
DATA = ROOT / "data"
DB_PATH = ROOT / "hifi.sqlite"
SKIPS = ROOT / "skips.jsonl"
LOG = ROOT / "fetch_hifi.log"
PAGES_JSON = DATA / "pages.json"

SF = ROOT / "node_modules/.bin/single-file"
CHROME = "/usr/bin/google-chrome-stable"
MONOLITH = ROOT / "bin" / "monolith"
if not MONOLITH.exists():
    MONOLITH = Path("/workspace/bookmark-db-hi-fi/bin/monolith")

BROWSER_ARGS = json.dumps(
    ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
)

MD_MAX_CHARS = 64000
MIN_HTML_BYTES = 2000
TIMEOUT_LOAD = "90000"
TIMEOUT_CAPTURE = "90000"
SF_TIMEOUT_SEC = 180
MONOLITH_TIMEOUT_SEC = 90
MAX_RESOURCE_MB = "2"
DELAY_SEC = 1.0  # between pages to ease RAM

TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"{now_iso()} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY,
            title TEXT,
            url TEXT,
            domain TEXT,
            cat1 TEXT,
            cat2 TEXT,
            source TEXT,
            fetched_at TEXT,
            status TEXT,
            method TEXT,
            http_status INTEGER,
            html_bytes INTEGER,
            md_bytes INTEGER,
            html_path TEXT,
            md_path TEXT,
            skip_reason TEXT,
            error TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hifi_status ON pages(status)")
    conn.commit()


def upsert(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO pages (
            id,title,url,domain,cat1,cat2,source,fetched_at,status,method,
            http_status,html_bytes,md_bytes,html_path,md_path,skip_reason,error
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title, url=excluded.url, domain=excluded.domain,
          cat1=excluded.cat1, cat2=excluded.cat2, source=excluded.source,
          fetched_at=excluded.fetched_at, status=excluded.status, method=excluded.method,
          http_status=excluded.http_status, html_bytes=excluded.html_bytes,
          md_bytes=excluded.md_bytes, html_path=excluded.html_path, md_path=excluded.md_path,
          skip_reason=excluded.skip_reason, error=excluded.error
        """,
        (
            row["id"], row["title"], row["url"], row["domain"], row["cat1"], row["cat2"],
            row["source"], row["fetched_at"], row["status"], row.get("method"),
            row.get("http_status"), row.get("html_bytes") or 0, row.get("md_bytes") or 0,
            row.get("html_path"), row.get("md_path"), row.get("skip_reason"), row.get("error"),
        ),
    )
    conn.commit()


def load_all_candidates(done_ids: set[int]):
    """All CSV rows; dedupe URL keep lowest id; apply should_skip_before_fetch."""
    rows = []
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    by_url: dict[str, dict] = {}
    dup_skips = []
    for row in rows:
        url = (row.get("网址") or "").strip()
        key = url.rstrip("/").lower()
        try:
            rid = int(row["序号"])
        except Exception:
            continue
        if key in by_url:
            existing = int(by_url[key]["序号"])
            if rid < existing:
                dup_skips.append({**by_url[key], "_skip": f"duplicate_of:{rid}"})
                by_url[key] = row
            else:
                dup_skips.append({**row, "_skip": f"duplicate_of:{existing}"})
        else:
            by_url[key] = row

    to_fetch, skipped = [], []
    already = 0
    for row in by_url.values():
        rid = int(row["序号"])
        if rid in done_ids:
            already += 1
            continue
        reason = should_skip_before_fetch(row)
        if reason:
            skipped.append({**row, "_skip": reason})
        else:
            to_fetch.append(row)
    for row in dup_skips:
        if int(row["序号"]) not in done_ids:
            skipped.append(row)

    to_fetch.sort(key=lambda r: int(r["序号"]))
    return to_fetch, skipped, already, len(rows)


def html_to_md(html_path: Path, md_path: Path) -> int:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            ["markitdown", str(html_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        text = r.stdout or ""
    except Exception as e:
        text = f"(markitdown failed: {e})\n"
    if len(text) > MD_MAX_CHARS:
        text = text[:MD_MAX_CHARS] + "\n\n…[truncated for index]…\n"
    md_path.write_text(text, encoding="utf-8")
    return md_path.stat().st_size


def run_single_file(url: str, out_html: Path) -> tuple[bool, str]:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    # remove stale partial
    if out_html.exists():
        try:
            out_html.unlink()
        except Exception:
            pass
    cmd = [
        str(SF),
        url,
        str(out_html),
        "--browser-executable-path", CHROME,
        "--browser-args", BROWSER_ARGS,
        "--browser-load-max-time", TIMEOUT_LOAD,
        "--browser-capture-max-time", TIMEOUT_CAPTURE,
        "--browser-wait-until", "networkIdle",
        "--max-resource-size-enabled", "true",
        "--max-resource-size", MAX_RESOURCE_MB,
        "--block-videos", "true",
        "--block-audios", "true",
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SF_TIMEOUT_SEC,
        )
        if out_html.exists() and out_html.stat().st_size >= MIN_HTML_BYTES:
            return True, ""
        err = (r.stderr or r.stdout or f"exit={r.returncode}")[-500:]
        return False, err.strip() or "empty_or_tiny"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"


def http_probe(url: str) -> tuple[int, bytes]:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=30, context=ctx) as resp:
            return getattr(resp, "status", 200) or 200, resp.read(5_000_000)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(100_000)
        except Exception:
            body = b""
        return int(e.code), body
    except Exception:
        return 0, b""


def run_monolith(url: str, out_html: Path) -> tuple[bool, str]:
    if not MONOLITH.exists():
        return False, "monolith_missing"
    out_html.parent.mkdir(parents=True, exist_ok=True)
    if out_html.exists():
        try:
            out_html.unlink()
        except Exception:
            pass
    cmd = [str(MONOLITH), "-o", str(out_html), "-a", "-j", url]  # -a no audio, -j no js? check
    # monolith: -a no audio, -v no video; keep defaults
    cmd = [str(MONOLITH), "-o", str(out_html), url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=MONOLITH_TIMEOUT_SEC)
        if out_html.exists() and out_html.stat().st_size >= MIN_HTML_BYTES:
            return True, ""
        return False, (r.stderr or r.stdout or "empty")[-400:]
    except subprocess.TimeoutExpired:
        return False, "monolith_timeout"
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"


def free_mem_mb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def fetch_one(row: dict) -> dict:
    rid = int(row["序号"])
    url = row["网址"].strip()
    title = (row.get("标题") or "").strip()
    domain = (row.get("域名") or host_of(url) or "").strip()
    html_path = HI / f"{rid}.html"
    md_path = MD / f"{rid}.md"
    base = {
        "id": rid,
        "title": title,
        "url": url,
        "domain": domain,
        "cat1": row.get("一级分类") or "",
        "cat2": row.get("二级分类") or "",
        "source": row.get("来源") or "",
        "fetched_at": now_iso(),
        "status": "fail",
        "method": None,
        "http_status": None,
        "html_bytes": 0,
        "md_bytes": 0,
        "html_path": None,
        "md_path": None,
        "skip_reason": None,
        "error": None,
    }

    # Wait if RAM critically low
    for _ in range(30):
        avail = free_mem_mb()
        if avail >= 1500:
            break
        log(f"low_mem id={rid} avail={avail}MiB; sleeping 10s")
        time.sleep(10)

    ok, err = run_single_file(url, html_path)
    method = "single-file"
    if not ok:
        # Monolith fallback only if HTTP returns real body (not 403/empty)
        status, body = http_probe(url)
        base["http_status"] = status
        if status == 200 and body and len(body) >= 500:
            # crude check not a challenge page
            low = body[:3000].decode("utf-8", errors="ignore").lower()
            if "just a moment" not in low and "cf-browser-verification" not in low:
                mok, merr = run_monolith(url, html_path)
                if mok:
                    ok = True
                    method = "monolith"
                    err = None
                else:
                    err = f"sf:{err}; mono:{merr}"
            else:
                err = f"sf:{err}; http_challenge"
        else:
            err = f"sf:{err}; http={status}/no_body"

    if ok:
        hb = html_path.stat().st_size
        mb = html_to_md(html_path, md_path)
        base.update({
            "status": "ok",
            "method": method,
            "html_bytes": hb,
            "md_bytes": mb,
            "html_path": f"content_html/{rid}.html",
            "md_path": f"content_md/{rid}.md",
            "error": None,
        })
    else:
        # cleanup tiny leftovers
        for p in (html_path, md_path):
            if p.exists() and p.stat().st_size < MIN_HTML_BYTES:
                try:
                    p.unlink()
                except Exception:
                    pass
        base.update({
            "status": "fail",
            "method": method,
            "error": (err or "unknown")[:800],
        })
    return base


def rebuild_pages_json(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT id,title,url,domain,cat1,cat2,source,fetched_at,status,method,"
        "http_status,html_bytes,md_bytes,html_path,md_path,skip_reason,error "
        "FROM pages ORDER BY id"
    )
    cols = [d[0] for d in cur.description]
    pages = [dict(zip(cols, r)) for r in cur.fetchall()]
    # UI expects fetch_status
    for p in pages:
        p["fetch_status"] = p["status"]
        p["chars"] = p.get("md_bytes") or 0
        p["summary"] = ""
    DATA.mkdir(parents=True, exist_ok=True)
    PAGES_JSON.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(pages)


def main() -> None:
    HI.mkdir(parents=True, exist_ok=True)
    MD.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=60)
    init_db(conn)

    # Resume: treat ok/skip/fail as done (fail can be retried with --retry-fail)
    retry_fail = "--retry-fail" in sys.argv
    if retry_fail:
        done_ids = {r[0] for r in conn.execute("SELECT id FROM pages WHERE status IN ('ok','skip')")}
    else:
        done_ids = {r[0] for r in conn.execute("SELECT id FROM pages")}

    # Also skip if HTML already exists and looks good (orphan resume)
    for p in HI.glob("*.html"):
        try:
            rid = int(p.stem)
            if p.stat().st_size >= MIN_HTML_BYTES and rid not in done_ids:
                # register as ok without re-fetch
                done_ids.add(rid)
        except Exception:
            pass

    to_fetch, skipped_pre, already, raw = load_all_candidates(done_ids)
    log(
        f"START raw={raw} already={already} skip_pre={len(skipped_pre)} "
        f"to_fetch={len(to_fetch)} avail_mem={free_mem_mb()}MiB"
    )

    with SKIPS.open("a", encoding="utf-8") as sf:
        for row in skipped_pre:
            rid = int(row["序号"])
            reason = row.get("_skip") or "skip"
            rec = {
                "id": rid,
                "title": (row.get("标题") or "").strip(),
                "url": (row.get("网址") or "").strip(),
                "domain": (row.get("域名") or host_of(row.get("网址") or "") or "").strip(),
                "cat1": row.get("一级分类") or "",
                "cat2": row.get("二级分类") or "",
                "source": row.get("来源") or "",
                "fetched_at": now_iso(),
                "status": "skip",
                "method": None,
                "http_status": None,
                "html_bytes": 0,
                "md_bytes": 0,
                "html_path": None,
                "md_path": None,
                "skip_reason": reason,
                "error": None,
            }
            upsert(conn, rec)
            sf.write(json.dumps({"id": rid, "reason": reason, "url": rec["url"]}, ensure_ascii=False) + "\n")

    ok_n = fail_n = 0
    total = len(to_fetch)
    for i, row in enumerate(to_fetch, 1):
        rid = int(row["序号"])
        try:
            result = fetch_one(row)
            upsert(conn, result)
            if result["status"] == "ok":
                ok_n += 1
                log(
                    f"OK {i}/{total} id={rid} method={result['method']} "
                    f"html={result['html_bytes']} md={result['md_bytes']}"
                )
            else:
                fail_n += 1
                log(f"FAIL {i}/{total} id={rid} err={(result.get('error') or '')[:120]}")
        except Exception as e:
            fail_n += 1
            err = f"{type(e).__name__}:{e}"
            log(f"EXC {i}/{total} id={rid} {err}")
            upsert(conn, {
                "id": rid,
                "title": (row.get("标题") or "").strip(),
                "url": (row.get("网址") or "").strip(),
                "domain": (row.get("域名") or "").strip(),
                "cat1": row.get("一级分类") or "",
                "cat2": row.get("二级分类") or "",
                "source": row.get("来源") or "",
                "fetched_at": now_iso(),
                "status": "fail",
                "method": None,
                "http_status": None,
                "html_bytes": 0,
                "md_bytes": 0,
                "html_path": None,
                "md_path": None,
                "skip_reason": None,
                "error": err[:800],
            })
        if i % 10 == 0:
            n = rebuild_pages_json(conn)
            log(f"progress {i}/{total} ok={ok_n} fail={fail_n} pages_json={n} mem={free_mem_mb()}MiB")
        time.sleep(DELAY_SEC)

    n = rebuild_pages_json(conn)
    cur = conn.execute(
        "SELECT status, COUNT(*) FROM pages GROUP BY status"
    )
    counts = dict(cur.fetchall())
    log(f"DONE ok={ok_n} fail={fail_n} db_counts={counts} pages_json={n}")
    conn.close()


if __name__ == "__main__":
    main()
