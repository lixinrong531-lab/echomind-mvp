# EchoMind MVP 部署指南

目标：拿到一个**公开测试链接**（手机浏览器可打开），用于真实用户测试和比赛现场演示。

## 方案一：Railway（推荐，5 分钟）

> 新账号有 30 天免费试用（含 $5 额度），不绑卡，对轻量应用够用。
> 试用到期后会转入每月 $1 额度的免费计划；长期正式运营再考虑付费。

### 准备工作（在电脑上操作，手机传文件不方便）

1. 注册 GitHub 账号：https://github.com（免费）。
2. 新建一个仓库（New repository），名字如 `echomind-mvp`，选 Public。
3. 把下面这个源码包下载、解压，把里面的所有文件上传到仓库：
   - 在仓库页面点 `Add file` → `Upload files`，把解压后的文件拖进去
     （注意保持文件夹结构：`static/`、`tools/` 等不要打散）。
   - 包里**不含音频文件**（10 首音乐在部署时会自动合成生成，约 18 秒），
     所以整个包只有约 1MB，上传很快。

### 部署

4. 注册 https://railway.app，建议点 `Login with GitHub`（用上面的 GitHub 账号）。
5. 点 `New Project` → `Deploy from GitHub repo` → 选择 `echomind-mvp` 仓库。
6. 配置构建和启动命令（在 Service 的 `Settings` 里）：
   - Build Command：`pip install -r requirements.txt && python tools/gen_music.py`
     （这一步会自动合成 10 首音乐，约 18 秒）
   - Start Command：`python app.py`
7. 在项目的 `Variables` 标签页添加：
   - `ADMIN_KEY`＝一个你自己定的管理后台密钥（不要用默认的 `echomind2026`）
   - `PORT`＝Railway 会自动注入，无需手动设置
8. 部署完成后，在 `Settings` → `Networking` 里点 `Generate Domain`，
   得到 `https://xxx.up.railway.app` 这样的公开地址。
9. 手机浏览器打开这个地址就是用户端；
   管理后台：`https://xxx.up.railway.app/admin`，输入你设的 `ADMIN_KEY`。

> 注意：Railway 免费服务的磁盘是临时的，SQLite 数据在重新部署后会丢失。
> 用户测试阶段建议：每次测试前在管理后台「导出 CSV」备份数据；
> 长期运行请挂载 Volume（Railway → Volume → 挂载到 `/app` 数据目录）
> 或改用 Railway 自带的 Postgres（需小幅改代码）。

## 方案二：Render（免费，操作类似）

1. 注册 https://render.com → New → Web Service → 连接 GitHub 仓库。
2. Build Command：`pip install flask`；Start Command：`python app.py`。
3. Environment 添加 `ADMIN_KEY`；Render 会自动注入 `PORT`。
4. 免费版 15 分钟无访问会自动休眠，首次打开稍慢（比赛演示前提前打开一次"热机"）。

## 方案三：自有服务器（长期）

```bash
# 服务器上
git clone <仓库地址> && cd echomind-mvp
python3 -m venv .venv && .venv/bin/pip install flask
ADMIN_KEY=你的密钥 PORT=5000 nohup .venv/bin/python app.py &
# 前面加 Nginx 反向代理 + HTTPS（略）
```

## 演示前检查清单

- [ ] 管理后台密钥已修改（不要用默认 `echomind2026`）
- [ ] 手机浏览器打开链接，全流程走一遍（选择 紧张8/10 → 考试前 → 平静下来 → 播放 → 反馈5/10）
- [ ] 确认音乐能正常播放（现场 Wi-Fi 不稳定可提前缓存：把 10 首 wav 在手机上播一遍）
- [ ] 导出一份 CSV，确认数据字段齐全（用于计划书"真实用户验证"章节）

## 知识产权

本项目全部代码、数据库结构、设计稿、音频文件、部署配置等成果的
知识产权归 Resomind 团队（项目负责人：李昕融）所有。
MVP 音频为程序合成，不存在版权争议，可自由使用、修改与分发。
