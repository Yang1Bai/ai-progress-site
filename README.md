# 🤖 AI Progress Hub

> **[English](#english) | [中文](#中文)**

---

<a name="english"></a>
## 🇬🇧 English

A daily automated summary of AI progress, powered by Claude API + Web Search. Covers 4 modules: **AI Leader Views · Daily AI News · AI4Science · AI4Materials**.

### 🌐 Access

**Live Site:** https://yang1bai.github.io/ai-progress-site/

**Archive:** https://yang1bai.github.io/ai-progress-site/archive/

**RSS Feed:** https://yang1bai.github.io/ai-progress-site/feed.xml

### ✨ Features

- 🤖 **Claude API + Web Search** — real daily search, not cached
- 🔗 **Source links** — every article links to original
- 📅 **Timestamped** — leader quotes with publication dates
- 📁 **Daily archive** — HTML + JSON snapshots

### 📊 Modules

| Module | Description |
|--------|-------------|
| 💬 **AI Leader Views** | Latest insights from Altman, LeCun, Hinton, Ng, and others |
| 📰 **Daily AI News** | Top AI developments of the day |
| 🔬 **AI4Science** | AI applications in scientific research |
| ⚗️ **AI4Materials** | AI for materials science and discovery |

### 🛠️ How It Works

GitHub Actions runs daily → Claude API searches the web → generates HTML → deploys to GitHub Pages.

### 📝 License

MIT License

---

<a name="中文"></a>
## 🇨🇳 中文

每日由 Claude API + Web Search 自动汇总四大模块：AI 大佬观点 · 今日 AI 大事 · AI4Science 进展 · AI4Material 论文。

### 🌐 在线访问

**主站：** https://yang1bai.github.io/ai-progress-site/

**历史归档：** https://yang1bai.github.io/ai-progress-site/archive/

**RSS 订阅：** https://yang1bai.github.io/ai-progress-site/feed.xml

### ✨ 特色功能

- 🤖 **Claude API + Web Search 驱动** — 每日自动搜索真实最新资讯
- 🔗 **新闻原文链接** — 每条新闻附带来源链接，一键跳转
- 📅 **领袖言论时间戳** — 显示观点发表日期
- 📁 **历史归档** — 每日 HTML 快照 + 原始 JSON，可随时回溯
- 📡 **RSS 订阅** — `feed.xml` 支持任意 RSS 阅读器
- 🔬 **严格 AI4Material 过滤** — 材料科学/催化/能源/化学，非材料论文不入库

### 📊 四大模块

| 模块 | 说明 |
|------|------|
| 💬 **AI 大佬观点** | Altman、LeCun、Hinton、吴恩达等领袖最新言论 |
| 📰 **今日 AI 大事** | 当日最重要的 AI 进展与新闻 |
| 🔬 **AI4Science** | AI 在科学研究领域的最新应用 |
| ⚗️ **AI4Materials** | AI 驱动材料科学与发现 |

### 🛠️ 工作原理

GitHub Actions 每日定时触发 → Claude API 调用 Web Search → 生成 HTML 报告 → 部署到 GitHub Pages。

### 架构

```
.
├── index.html                    # 主页（深色科技感 UI）
├── feed.xml                      # RSS/Atom 订阅源（自动生成）
├── .nojekyll
├── README.md
├── data/
│   ├── index.json                # 归档日期列表（自动生成）
│   ├── latest.json               # 最新一期原始 JSON
│   └── YYYY-MM-DD.json           # 每日原始数据归档
├── archive/
│   ├── index.html                # 归档目录页（自动生成）
│   └── YYYY-MM-DD.html           # 每日 HTML 快照
├── scripts/
│   ├── fetch_content.py          # 调用 Claude API + web_search 抓取最新内容
│   └── icons.py                  # SVG 图标定义
└── .github/workflows/update.yml  # 每日 cron 触发，运行脚本并自动 commit
```

`index.html` 中四个区块用 HTML 注释做锚点，脚本只替换标记之间的内容：

```html
<!-- LEADERS:START --> ... <!-- LEADERS:END -->
<!-- NEWS:START -->    ... <!-- NEWS:END -->
<!-- SCIENCE:START --> ... <!-- SCIENCE:END -->
<!-- MATERIAL:START --> ... <!-- MATERIAL:END -->
```

### 部署清单（按顺序做完一次即可）

#### 1. 推送代码到仓库

把本目录所有文件推送到 `Yang1Bai/ai-progress-site` 的 `main` 分支。注意 `.nojekyll` 是隐藏文件别漏。

#### 2. 配置 Anthropic API Key（关键）

在仓库 → **Settings → Secrets and variables → Actions** → 点击 **New repository secret**：

- **Name**：`ANTHROPIC_API_KEY`
- **Secret**：粘贴你在 https://console.anthropic.com/settings/keys 创建的 API key（以 `sk-ant-` 开头）

#### 3. 打开 Actions 写权限

仓库 → **Settings → Actions → General** → 滚到底 → **Workflow permissions** → 选 **Read and write permissions** → Save。

#### 4. 启用 GitHub Pages（如未启用）

仓库 → **Settings → Pages** → Source 选 *Deploy from a branch* → 分支 `main` / `(root)` → Save。

#### 5. 手动触发一次 Action 验证

仓库 → **Actions** → 左侧 **Daily AI progress update** → 右上 **Run workflow** → 点绿色按钮。
等 1-2 分钟，看到绿色 ✅ 后访问网站。

### 成本估算

模型默认 `claude-sonnet-4-5`，启用 `web_search`（最多 12 次）：
- 每次运行约 ~12K input + ~4K output tokens + ~12 次搜索
- 单次成本约 **$0.15–0.20**
- 每天跑 1 次 → **每月 ~$5-6**

如果想更省，把 `update.yml` 里的 `ANTHROPIC_MODEL` 改成 `claude-haiku-4-5`，大约能降到月 $1-2。

### 本地开发 / 调试

不调 API 验证模板逻辑：

```bash
DRY_RUN=1 python scripts/fetch_content.py
```

调真 API：

```bash
export ANTHROPIC_KEY=sk-ant-...
python scripts/fetch_content.py
```

### 已知限制

- 内容质量依赖 Claude 的 web_search 结果。如发现错误，可在仓库提 Issue 或手动修正。
- 新闻 URL 为 Claude 搜索到的原文链接；偶尔可能有链接失效，属正常现象。
- 可以编辑 `scripts/fetch_content.py` 里的 `USER_PROMPT_TEMPLATE` 调整内容偏好。

### 📝 开源协议

MIT License
