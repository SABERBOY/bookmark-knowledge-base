# Bookmark Hi-Fi archive (SingleFile)

## Run / resume
```bash
cd /workspace/bookmark-db-hi-fi
python3 -u tools/fetch_hifi_bulk.py            # resume: skips ids already in hifi.sqlite
python3 -u tools/fetch_hifi_bulk.py --retry-fail   # also retry previous fails
```

Log: `fetch_hifi.log`  
PID file: `fetch_hifi.pid`  
Progress DB: `hifi.sqlite`  
Artifacts: `content_html/{id}.html`, `content_md/{id}.md`  
Browse UI: `index.html` + `data/pages.json`

## Orchestrator
`tools/after_chunk3_and_start_hifi.sh <chunk3_pid>` waits for old MD chunk3, zips/uploads site sync/CF redeploy, then starts hi-fi.
