#!/usr/bin/env bash
set -euo pipefail
CHUNK_PID="${1:-97424}"
LOG=/workspace/bookmark-db-hi-fi/orchestrator.log
exec >>"$LOG" 2>&1
echo "$(date '+%F %T %z') orchestrator start; wait chunk3 pid=$CHUNK_PID"

# Wait for chunk3 if still running
if kill -0 "$CHUNK_PID" 2>/dev/null; then
  while kill -0 "$CHUNK_PID" 2>/dev/null; do
    sleep 30
    echo "$(date '+%F %T %z') waiting chunk3… $(tail -1 /workspace/bookmark-db/fetch_chunk3.log 2>/dev/null || true)"
  done
  echo "$(date '+%F %T %z') chunk3 exited"
else
  echo "$(date '+%F %T %z') chunk3 already gone"
fi

# Finish MD pipeline: rebuild pages.json, zip, upload, CF redeploy
cd /workspace/bookmark-db
python3 - << 'PY'
import json, sqlite3
from pathlib import Path
ROOT = Path("/workspace/bookmark-db")
DB = ROOT / "bookmarks.sqlite"
DATA = ROOT / "data"
PAGES = DATA / "pages.json"
conn = sqlite3.connect(DB)
cur = conn.execute(
    "SELECT id,title,url,domain,cat1,cat2,source,fetched_at,fetch_status,http_status,chars,summary,md_path,skip_reason FROM pages ORDER BY id"
)
cols = [d[0] for d in cur.description]
pages = [dict(zip(cols, r)) for r in cur.fetchall()]
DATA.mkdir(parents=True, exist_ok=True)
PAGES.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
from collections import Counter
c = Counter(p["fetch_status"] for p in pages)
print(f"pages={len(pages)} status={dict(c)}")
conn.close()
PY

# Zip only chunk3 new content if we can; else zip all content as content_chunk3.zip
# Prefer ids that are in chunk3 scope. For simplicity zip all MD not in chunk1/2 zip lists if available.
python3 - << 'PY'
import json, zipfile
from pathlib import Path
ROOT = Path("/workspace/bookmark-db")
CONTENT = ROOT / "content"
out = ROOT / "content_chunk3.zip"
# ids already in chunk1+2 from data files if present
known = set()
for name in ("chunk1_content_ids.json", "chunk2_new_ids.json"):
    p = ROOT / "data" / name
    if p.exists():
        data = json.loads(p.read_text())
        if isinstance(data, list):
            known.update(int(x) for x in data)
        elif isinstance(data, dict):
            known.update(int(x) for x in data.get("ids", data.keys()))
md_files = sorted(CONTENT.glob("*.md"))
chunk3 = []
for f in md_files:
    try:
        rid = int(f.stem)
    except Exception:
        continue
    if rid not in known:
        chunk3.append(f)
# If known empty, zip everything newer than chunk2 zip mtime — fallback: all md
if not known:
    chunk3 = md_files
print(f"zipping {len(chunk3)} md files -> content_chunk3.zip")
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for f in chunk3:
        z.write(f, arcname=f"content/{f.name}")
print(f"zip size={out.stat().st_size}")
# save ids
(ROOT/"data"/"chunk3_new_ids.json").write_text(json.dumps([int(f.stem) for f in chunk3]), encoding="utf-8")
PY

echo "$(date '+%F %T %z') chunk3 zip ready"

# Sync bookmark-site public from bookmark-db (MD site)
rm -rf /workspace/bookmark-site/public/content; cp -a /workspace/bookmark-db/content /workspace/bookmark-site/public/content
cp -a /workspace/bookmark-db/data/pages.json /workspace/bookmark-site/public/data/pages.json
cp /workspace/bookmark-db/data/pages.json /workspace/bookmark-site/public/pages.json
cp /workspace/bookmark-db/index.html /workspace/bookmark-site/public/index.html
echo "$(date '+%F %T %z') site synced"

# Cloudflare deploy
cd /workspace/bookmark-site
if [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
  npx --yes wrangler deploy 2>&1 | tee /workspace/bookmark-db/cf_deploy_chunk3.log | tail -20
  echo "$(date '+%F %T %z') CF deploy done"
else
  echo "$(date '+%F %T %z') CF token missing; skip deploy"
fi

# Write chunk3 report stub
python3 - << 'PY'
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json, sqlite3
TZ = timezone(timedelta(hours=8))
ROOT = Path("/workspace/bookmark-db")
conn = sqlite3.connect(ROOT/"bookmarks.sqlite")
cur = conn.execute("SELECT fetch_status, COUNT(*) FROM pages GROUP BY fetch_status")
counts = dict(cur.fetchall())
n = sum(counts.values())
conn.close()
ids = json.loads((ROOT/"data"/"chunk3_new_ids.json").read_text()) if (ROOT/"data"/"chunk3_new_ids.json").exists() else []
report = f"""# Chunk 3 Report — 非「开发与技术」分类

- Finished: **{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} Asia/Shanghai**
- Drive folder: https://drive.google.com/drive/folders/1DvQJJVpZldXbRaxOdddc0tTKcekJXzvy
- Method: trafilatura + jina proxy (final MD chunk). Hi-fi SingleFile pipeline starts after this.

## Counts (full DB after chunk3)

| Metric | N |
|--------|---|
| Pages in SQLite | {n} |
| Status breakdown | {counts} |
| Chunk3 MD files in zip | {len(ids)} |

## Artifacts

- content_chunk3.zip
- bookmarks.sqlite / data/pages.json
- CF: https://bookmark-knowledge-base.saberlovewuhao.workers.dev
"""
(ROOT/"CHUNK3_REPORT.md").write_text(report, encoding="utf-8")
print(report)
PY

# Mark old MD pipeline stopped (no more categories)
touch /workspace/bookmark-db/PIPELINE_STOPPED
echo "$(date '+%F %T %z') old MD pipeline stopped marker written"

# Free a bit of page cache if possible (best-effort)
sync || true

# Start hi-fi bulk (1 Chrome worker; script is sequential)
AVAIL=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
echo "$(date '+%F %T %z') starting hi-fi; MemAvailable=${AVAIL}MiB"
cd /workspace/bookmark-db-hi-fi
nohup python3 -u tools/fetch_hifi_bulk.py >> fetch_hifi.log 2>&1 &
echo $! > /workspace/bookmark-db-hi-fi/fetch_hifi.pid
echo "$(date '+%F %T %z') hi-fi pid=$(cat /workspace/bookmark-db-hi-fi/fetch_hifi.pid)"
