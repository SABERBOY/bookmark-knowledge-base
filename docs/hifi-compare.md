# High-fidelity HTML+MD pilot vs trafilatura MD

Date: 2026-11-06 (Asia/Shanghai)  
Work dir: `/workspace/bookmark-db-hi-fi/`  
Old pipeline still running: `bookmark-db` chunk3 (untouched).

## Tools installed

| Tool | Status | Notes |
|------|--------|-------|
| `single-file-cli` (npm local) | OK | Uses system Chrome `--no-sandbox` |
| `monolith` v2.10 binary | OK | Fast HTTP fetch; fails on 403 / JS-heavy |
| `markitdown` | OK | Convert saved HTML → MD |
| `pandoc` | Not in apt | Skipped; markitdown enough for pilot |

## Samples

| ID | Site | SingleFile | Monolith | Old trafilatura MD | MD from SingleFile HTML | URL→markitdown |
|----|------|------------|----------|--------------------|-------------------------|----------------|
| 1 | nvjob water shader | **8.79 MB** | 21.83 MB | 2.1 KB | **92.5 KB** | 4.4 KB |
| 2 | github.com/1by3/ELEMENTS | **8.01 MB** | 9.92 MB | 3.7 KB | **17.5 KB** | 12.5 KB |
| 3 | redblobgames visibility | **730 KB** | 168 KB | 11 KB | **16.6 KB** | 16.7 KB |
| 35 | Unity Addressables docs | **3.74 MB** | 8.7 KB (broken) | 2.2 KB | **10.4 KB** | 2.4 KB |
| 18 | 简书 EzySlice | **3.94 MB** | FAIL 403 | 4.1 KB | **13.8 KB** | FAIL |
| 1883 | ArtStation profile | **22.5 MB** | FAIL 403 | 16.3 KB | 10.6 KB | FAIL |

## Fidelity verdict (layout)

### SingleFile (primary) — **clearly better for browsing**
- Self-contained HTML with inlined CSS/fonts/images (`data:image` / CSS vars).
- Opens offline in a browser and looks close to the live page (nav, cards, docs chrome).
- Works where plain HTTP scrapers get **403** (简书, ArtStation) because it uses a real Chrome session.
- Unity docs: Monolith returned a near-empty shell (~9 KB); SingleFile captured full styled docs (~3.7 MB).

### Monolith — **optional fallback only**
- Faster, no browser; good on static/simple pages (Red Blob OK).
- Useless on bot-blocked or JS-rendered docs in this pilot.
- Sometimes larger than SingleFile (nvjob 22 MB) with similar content.

### markitdown from SingleFile HTML — **better structure than trafilatura**
- More headings / links / images than old MD (e.g. GitHub: 30 headings vs 1; nvjob MD 92 KB vs 2 KB).
- Still not a visual replica — MD is for search/skim; **HTML is the browse source**.
- URL-direct markitdown often thinner or fails (简书/ArtStation).

### Old trafilatura MD — **readable text only**
- Tiny files, lost layout, nav, figures, code chrome.
- Matches user complaint (“格式乱 / 跟原站差很多”).

## Size / ops risks for bulk (~3800 URLs)

- Typical SingleFile page: **~1–9 MB**; image-heavy SPA (ArtStation): **20+ MB**.
- Naïve full crawl could be **tens of GB**. Mitigations for production:
  - Cap images (`--max-resource-size-bytes`, lower quality / block fonts if needed).
  - Skip pure homepages / login walls (same skip list as before).
  - Store HTML as primary; MD capped (~32–64 KB) for search index.
  - Parallelism low (1–2 Chrome workers) to avoid OOM.
  - Timeout 60–90s; record failures, don’t block the batch.

## Recommendation for bulk pipeline

**Yes — switch browse path to SingleFile HTML; keep MD secondary.**

1. **Fetch**: `single-file-cli` + system Chrome (`--no-sandbox`, `networkIdle`, 90s caps).
2. **Primary artifact**: `content/{id}.html` (self-contained).
3. **Secondary**: `markitdown content/{id}.html → content/{id}.md` (search/summary; truncate if huge).
4. **Monolith**: optional fast path only when SingleFile fails *and* HTTP 200 returns real body.
5. **UI**: `index.html` open `.html` first; MD as “纯文本” toggle.
6. **Do not wipe** existing trafilatura MD until hi-fi re-fetch for that id succeeds.
7. **Cloudflare**: redeploy only after a small hi-fi batch is approved (not this pilot).

## Paths

```
/workspace/bookmark-db-hi-fi/
  hi/{id}.single.html      # primary fidelity samples
  hi/{id}.monolith.html    # optional
  hi/{id}.from_single.md   # markitdown(saved HTML)  ← prefer
  hi/{id}.full.md          # markitdown(URL)         ← weaker
  old/{id}.trafilatura.md  # previous pipeline copies
  compare_raw.json
  fetch_samples.sh
  tools/fetch_hifi_outline.py
  COMPARE_HIFI.md          # this file
```

Open a sample locally:
```bash
# e.g. Red Blob (small) or nvjob
xdg-open /workspace/bookmark-db-hi-fi/hi/3.single.html
```
