# 书签知识库 · Bookmark Knowledge Base

Bender Wu 的个人书签知识库静态站：把 Chrome 书签抓成可检索、可深读的「数字花园」。

当前线上 Worker（若已部署）使用 `public/` 里的**旧版列表页**；A+B 混搭的新首页在 `site/`，尚未切到正式部署目录。

## 仓库结构

```
.
├── public/                 # Wrangler 正式静态资源目录（当前部署用）
│   ├── index.html          # 旧版列表+详情页（legacy，与线上一致）
│   ├── legacy.html         # 同上备份文件名
│   ├── pages.json          # 3839 条书签元数据
│   ├── data/pages.json     # 同上副本（兼容旧路径）
│   ├── content/*.md        # 抓取正文（Markdown，约 25MB）
│   └── hifi-ids.json       # 已有高保真 HTML 的 id 列表（正文 HTML 不入库）
├── site/                   # 新「书签花园」首页（Maggie×Josh×Andy 混搭预览）
│   ├── index.html
│   └── hifi-ids.json
├── tools/                  # 高保真 / 编排脚本
│   ├── fetch_hifi_bulk.py
│   ├── fetch_hifi_outline.py
│   └── …
├── docs/                   # 说明与预览截图
├── wrangler.jsonc          # Cloudflare Workers Assets 配置
└── package.json
```

## 本地预览

**旧版（与当前 `public/` 一致）：**

```bash
cd public
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/
```

**新花园首页（`site/`，会回退读取 `../public` 的数据与 MD）：**

```bash
# 在仓库根目录
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/site/
```

把新首页提升为正式首页（可选，需自行决定后再部署）：

```bash
cp public/index.html public/legacy.html   # 若尚未备份
cp site/index.html public/index.html
# 按需把 hifi/ 目录放到 public/hifi/（本仓库默认不包含 SingleFile HTML）
```

## 部署到 Cloudflare（Workers 静态资源）

需要本机已登录 Wrangler，或设置环境变量 `CLOUDFLARE_API_TOKEN`（**不要**把 token 写进仓库）。

```bash
npm i
npx wrangler deploy
```

`wrangler.jsonc` 中的 `account_id` 可以保留；真正的 API Token / OAuth 凭据只应存在于本机环境或 CI Secret。

## 未纳入本仓库的内容

为控制体积与避免噪音，以下默认**不提交**（见 `.gitignore`）：

- SingleFile / Monolith **高保真 HTML**（体积常达数百 MB～GB）
- SQLite 数据库、zip/tar、日志、pid
- `node_modules/`、`.wrangler/`
- `.env` 与任何 token / cookie / 私钥

正文 **Markdown**（`public/content/`）已纳入，合计约 25MB，单文件远小于 50MB。

## 数据说明

- `pages.json` 字段大致含：`id, title, url, domain, cat1, cat2, summary, md_path, fetch_status, chars, …`
- 分类示例：开发与技术、设计与美术、学习与知识、工具与效率等
- 高保真 HTML 需用 `tools/fetch_hifi_*.py` 在本地另行抓取后放到 `public/hifi/{id}.html`

## License

个人书签归档；第三方页面版权归原站点所有。抓取正文仅供私人检索与阅读备份。


## 高保真 HTML（本地 / 部署快照）

SingleFile 抓取产物默认**不进 Git**（体积大，且有文件超过 Workers 单文件 25 MiB 上限）。

```bash
# 从 content_html 生成可部署 id 列表，并复制 ≤25MiB 的 HTML 到 public/hifi/
python3 tools/build_hifi_ids.py \
  --html-dir /path/to/content_html \
  --out public/hifi-ids.json \
  --report docs/hifi-oversized.json \
  --copy-to public/hifi
```

超过 25 MiB 的页面不会复制，详情页回退 Markdown。抓取仍在进行时可随时重跑脚本再 `npx wrangler deploy`。
