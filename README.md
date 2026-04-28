# AI Progress Hub · ai-progress-site

每日由 Claude API + Web Search 自动汇总三大模块：AI 大佬观点 · 今日 AI 大事 · AI4Science 进展。

## 在线访问

`https://yang1bai.github.io/ai-progress-site/`

---

## 架构

```
.
├── index.html                    # 主页（深色科技感 UI）
├── .nojekyll
├── README.md
├── scripts/
│   └── fetch_content.py          # 调用 Claude API + web_search 抓取最新内容
└── .github/workflows/update.yml  # 每日 cron 触发，运行脚本并自动 commit
```

`index.html` 中三个区块用 HTML 注释做锚点，脚本只替换标记之间的内容：

```html
<!-- LEADERS:START --> ... <!-- LEADERS:END -->
<!-- NEWS:START -->    ... <!-- NEWS:END -->
<!-- SCIENCE:START --> ... <!-- SCIENCE:END -->
```

---

## 部署清单（按顺序做完一次即可）

### 1. 推送代码到仓库

把本目录所有文件推送到 `Yang1Bai/ai-progress-site` 的 `main` 分支。注意 `.nojekyll` 是隐藏文件别漏。

### 2. 配置 Anthropic API Key（关键）

在仓库 → **Settings → Secrets and variables → Actions** → 点击 **New repository secret**：

- **Name**：`ANTHROPIC_API_KEY`
- **Secret**：粘贴你在 https://console.anthropic.com/settings/keys 创建的 API key（以 `sk-ant-` 开头）

### 3. 打开 Actions 写权限

仓库 → **Settings → Actions → General** → 滚到底 → **Workflow permissions** → 选 **Read and write permissions** → Save。

### 4. 启用 GitHub Pages（如未启用）

仓库 → **Settings → Pages** → Source 选 *Deploy from a branch* → 分支 `main` / `(root)` → Save。

### 5. 手动触发一次 Action 验证

仓库 → **Actions** → 左侧 **Daily AI progress update** → 右上 **Run workflow** → 点绿色按钮。
等 1-2 分钟，看到绿色 ✅ 后访问网站，三大模块应该已是最新内容。

---

## 成本估算

模型默认 `claude-sonnet-4-5`，启用 `web_search`（最多 6 次）：
- 每次运行约 ~10K input + ~3K output tokens + ~6 次搜索
- 单次成本约 **$0.10–0.15**
- 每天跑 1 次 → **每月 ~$3-5**

如果想更省，把 `update.yml` 里的 `ANTHROPIC_MODEL` 改成 `claude-haiku-4-5`，大约能降到月 $1。

---

## 本地开发 / 调试

不调 API 验证模板逻辑：

```bash
DRY_RUN=1 python scripts/fetch_content.py
```

调真 API：

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/fetch_content.py
```

---

## 已知限制

- 内容质量依赖模型搜索结果。如发现错误，可在仓库提 Issue 或手动修正后下次自动覆盖。
- Web search 偶尔可能抓不到结果，脚本会基于训练知识合理整理（已在 prompt 里要求不编造具体数字/论文名）。
- 可以编辑 `scripts/fetch_content.py` 里的 `USER_PROMPT_TEMPLATE` 调整内容偏好。
