# Dayang Podcast — 部署流程

> 本文档面向 Stan（后端）和 Dana（前端），说明代码修改如何到达生产环境。

---

## 架构概览

```
你改代码 → git push → GitHub (main)
                        ↓
             ┌──────────┴──────────┐
             ↓                      ↓
        Vercel (auto-deploy)    Mac Mini (Docker rebuild)
        前端静态页面              API 后端容器
```

- **前端**：Vercel 自动部署（推送 main 即生效）
- **后端**：需手动在 Mac Mini 上运行部署脚本（GitHub Actions 自托管 runner 可选）

---

## 开发工作流

### 1. 修改代码

```bash
# 进入项目目录
cd ~/projects/dayang-podcast

# 修改代码...然后提交
git add -A
git commit -m "你的修改说明"
git push origin main
```

### 2. 前端更新（自动）

推送后等待约 1 分钟，Vercel 自动构建并部署：
- **URL**：https://dayang-podcast-frontend.vercel.app
- 无需手动操作，可在 Vercel Dashboard 查看部署进度

### 3. 后端更新（需手动）

SSH 到 Mac Mini（或直接在本地终端），运行：

```bash
bash scripts/deploy.sh
```

这个脚本会：
1. `git pull origin main` — 拉取最新代码
2. `docker-compose build api` — 重建 API 镜像
3. `docker-compose up -d api` — 重启容器
4. 健康检查 + 冒烟测试

---

## 文件位置说明

| 内容 | 路径 |
|------|------|
| API 后端代码 | `app/` 目录 |
| 前端静态页面 | `app/static/index.html` |
| Docker 配置 | `docker-compose.yml` |
| 一键部署脚本 | `scripts/deploy.sh` |
| GitHub Actions（可选） | `.github/workflows/deploy.yml` |

> **⚠️ 重要**：前端代码也存放在这个仓库的 `app/static/` 中，不要在其他地方单独修改前端 HTML。

---

## 紧急回滚

如果生产环境出问题：

```bash
# 回退到上一个版本
git revert HEAD
git push origin main

# 重启后端
bash scripts/deploy.sh
```

或直接重启容器到上一个镜像：

```bash
docker-compose down api
docker-compose up -d api  # 使用已缓存的旧镜像
```

---

## Vercel 部署配置

- **Framework**: Other
- **Output Directory**: `app/static/`
- **Build Command**: (skip)
- **Install Command**: (skip)
- **Git Integration**: Connected to GitHub repo, branch `main`

---

## 监控

- API 健康检查：`GET https://api.myagent.ccwu.cc/health`
- 生产前端：`https://dayang-podcast-frontend.vercel.app`
