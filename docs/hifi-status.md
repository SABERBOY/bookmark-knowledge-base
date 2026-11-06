# Hi-Fi crawl — stable (2026-11-06 17:32:55 +0800 Asia/Shanghai)

- Script: `/workspace/bookmark-db-hi-fi/tools/fetch_hifi_bulk.py`
- Resume: `cd /workspace/bookmark-db-hi-fi && python3 -u tools/fetch_hifi_bulk.py` (`--retry-fail` optional)
- Log: `/workspace/bookmark-db-hi-fi/fetch_hifi.log`
- PID: 121065 (running=yes)
- Progress DB: `hifi.sqlite` — ok/fail/skip tracked; skip_pre=1267, to_fetch=2572
- HTML files on disk: 42
- Sample: id1=5.1M, id2=616K, id3=646K
- Mem healthy (~9Gi available); 1 Chrome worker; no OOM
- CF hi-fi deploy: deferred (parent owns MD CF; wait for more pages)
- Old trafilatura MD under bookmark-db/content: untouched
