# AI Progress Hub · ai-progress-site

聚焦 AI 领袖观点、每日大事与 AI4Science 发展的静态站点。

## 在线访问

启用 GitHub Pages 后访问：`https://yang1bai.github.io/ai-progress-site/`

## 部署步骤（关键，请按顺序执行）

1. 把本目录的所有文件覆盖推送到仓库 `Yang1Bai/ai-progress-site` 的 `main` 分支。
2. 打开仓库 → **Settings** → **Pages**。
3. 在 *Build and deployment* 中：
   - Source 选 **Deploy from a branch**
   - Branch 选 **main**，文件夹选 **/ (root)**，保存。
4. 等待 1–2 分钟构建完成，访问上面的链接即可。
5. 打开 **Settings → Actions → General**，把 *Workflow permissions* 设置为 **Read and write permissions**，否则定时更新无法 push。

## 本次修复的问题

| # | 问题 | 修复 |
|---|------|------|
| 1 | GitHub Action 中 `DATE` 变量在步骤间丢失，导致 commit message 为空且替换无效 | 改为 `steps.date.outputs.date` 跨步骤传递 |
| 2 | workflow 缺少 `contents: write` 权限，`git push` 会被拒绝 | 顶层 `permissions: contents: write` |
| 3 | `actions/checkout@v3` 已过时 | 升级到 `@v4` |
| 4 | 正文里残留 `【数字†screenshot】` 这种研究标记 | 全部清理 |
| 5 | 多位领袖共用同一张 `leader_avatar.png`，且大体积 PNG 影响加载 | 用纯 CSS 渐变 + 文字 / 内联 SVG 图标替换 |
| 6 | UI 朴素 | 重写为深色科技感设计：渐变背景、玻璃拟态卡片、滚动动画、响应式 |

## 文件结构

```
.
├── index.html              # 主页（深色科技感 UI）
├── .nojekyll               # 跳过 Jekyll 处理，避免下划线开头文件被忽略
├── README.md               # 本文件
└── .github/
    └── workflows/
        └── update.yml      # 每日更新「今日AI大事」日期的 Action
```

## 自动更新逻辑

`update.yml` 每天 UTC 12:00（多伦多 8:00 / 北京 20:00）触发，将
`<span id="last-updated">YYYY年M月D日</span>` 中的日期替换为当天日期并自动 commit。
也支持在 Actions 页面手动触发（workflow_dispatch）。

## 后续可优化

- 把「今日AI大事」从静态文本改为 Action 调用模型生成 / RSS 抓取自动写入。
- 加入暗/浅色切换。
- 接入 Google Analytics / Umami 做访问统计。
