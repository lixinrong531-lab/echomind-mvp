# EchoMind MVP —— 让每一次情绪波动，都有一首懂你的歌

大学生创新创业比赛（国创赛）最小可行产品（MVP）。

**核心概念**：让音乐推荐从"你喜欢什么"变成"你现在需要什么"。
用户输入当前情绪状态 + 使用场景 + 目标状态，系统按"情绪 + 场景 + 音乐特征"
规则匹配，生成三段渐进式音乐调节路径；使用结束后用户再次评价状态，
形成"输入 — 推荐 — 使用 — 反馈"的完整闭环，并沉淀真实用户数据。

## 一、快速开始

```bash
cd echomind-mvp
python3 -m venv .venv
.venv/bin/pip install flask numpy pillow   # numpy/pillow 仅用于生成音乐素材
.venv/bin/python tools/gen_music.py         # 生成 10 首合成音乐 + 封面（只需跑一次）
.venv/bin/python tools/seed.py             # 初始化数据库曲目（可重复执行）
.venv/bin/python app.py                    # 启动服务
```

- 用户端：http://localhost:5000
- 管理后台：http://localhost:5000/admin（密钥见下）
- 端口可通过环境变量 `PORT` 修改；管理密钥通过环境变量 `ADMIN_KEY` 设置，
  默认 `echomind2026`（演示用，公开发布前请务必修改）。

手机浏览器直接打开服务器地址即可使用（响应式设计，无任何外部 CDN，离线可用）。

## 二、目录结构

```
echomind-mvp/
├── app.py                 # Flask 后端：API + 管理后台 + CSV 导出
├── recommender.py         # 推荐引擎（规则 + 标签匹配，可解释文案）
├── echomind.db            # SQLite 数据库（首次启动自动创建）
├── tools/
│   ├── gen_music.py       # 程序合成 10 首氛围音乐 + 封面 + tracks.json
│   ├── seed.py            # 数据库初始化（建表 + 写入种子曲目）
│   └── tracks.json        # 曲目种子数据
├── static/
│   ├── index.html         # 用户端单页应用（9 屏流程）
│   ├── app.js             # 用户端逻辑（无外部依赖）
│   ├── admin.html         # 管理后台页面
│   ├── admin.js           # 管理后台逻辑（无外部依赖）
│   ├── style.css          # 全站样式（浅蓝→蓝紫，移动优先）
│   ├── audio/             # 10 首 WAV（22050Hz 单声道，程序合成）
│   └── covers/            # 10 张封面 PNG（程序生成）
└── README.md
```

## 三、数据库结构（SQLite）

| 表 | 字段 | 说明 |
|---|---|---|
| `users` | `id` TEXT PK, `created_at`, `nickname` | 用户，id 为前端 localStorage 生成的 UUID |
| `tracks` | `id` INTEGER PK, `title`, `file`, `cover`, `bpm`, `rhythm_type`, `stimulation`, `timbre`, `has_vocal`, `emotion_tags`(JSON), `scene_tags`(JSON), `stage`, `enabled`, `created_at` | 曲目库：BPM / 节奏类型 / 刺激度 / 音色 / 有无人声 / 情绪标签 / 场景标签 / 推荐阶段 |
| `sessions` | `id` TEXT PK, `user_id`, `created_at`, `emotion`, `intensity_before`, `scene`, `goal`, `plan_json`(推荐方案快照), `intensity_after`, `duration_sec`, `completed` | 每次使用会话：情绪 / 强度 / 场景 / 目标 / 前后评分 / 时长 |
| `events` | `id` INTEGER PK, `session_id`, `track_id`, `action`(play/pause/skip/complete), `position_sec`, `created_at` | 播放行为打点 |

每次使用至少记录：用户ID、时间、当前情绪、情绪强度、使用场景、目标状态、
推荐方案、播放曲目、播放时长、是否跳过、使用后情绪、使用后强度——全部落库，
可在管理后台查看并导出 CSV。

## 四、API 说明

### 用户端

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/session/start` | 开始调节。Body: `{user_id, emotion, intensity_before(1-10), scene, goal}` → `{session_id, plan:{stages:[{stage, track, reason}], explanation}}` |
| POST | `/api/session/<id>/event` | 打点。Body: `{track_id, action: play\|pause\|skip\|complete, position_sec}` |
| POST | `/api/session/<id>/finish` | 结束并反馈。Body: `{intensity_after(1-10), duration_sec}` → `{intensity_before, intensity_after, delta}` |
| GET | `/api/history?user_id=` | 该用户历史 sessions（含前后评分、时长、方案） |
| GET | `/api/tracks` | 已启用的曲目列表 |

### 管理后台（鉴权：请求头 `X-Admin-Key` 或 `?key=`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/stats` | 用户数 / 使用次数 / 情绪分布 / 场景分布 / 使用前·后平均分 / 分场景前后变化 / 分曲目播放次数 |
| GET/POST | `/api/admin/tracks` | 曲目列表 / 新增曲目 |
| PUT/DELETE | `/api/admin/tracks/<id>` | 修改曲目及标签 / 删除曲目 |
| GET | `/api/admin/sessions` | 会话明细（含打点次数） |
| GET | `/api/admin/export.csv` | 导出全部会话 + 事件汇总 CSV（UTF-8 BOM，Excel 可直接打开） |

### 推荐规则摘要

目标 → 三阶段路径：

- 平静下来 → 释放 → 稳定 → 放松
- 放松 → 稳定 → 放松 → 放松
- 专注 → 稳定 → 专注 → 稳定
- 恢复能量 → 释放 → 能量 → 稳定
- 暂时不想思考 → 放松 → 放松 → 稳定

每阶段按阶段过滤曲目，优先场景标签精确命中当前场景的曲目，
"通用"标签兜底；同一 session 内三首不重复。
场景标签经过调校以体现核心创新：例如"紧张 + 考试前"与"紧张 + 演出前"
在"释放"阶段会分别命中《晨雾释放》与《潮汐释放》——
同一种情绪，在不同场景下得到不同的音乐方案。

**文案合规**：全站严禁医疗承诺，不出现"治疗 / 疗效 / 保证降低心率 /
检测出焦虑症"等表述；效果一律描述为"主观感受变化"。

## 五、演示流程（约 1–2 分钟）

首页"开始一次情绪调节" → 选"紧张"、强度 8 → 选"考试前" →
选"平静下来" → 查看三段路径与推荐理由 → 开始聆听
（可随时"下一首"跳过）→ 结束调节 → 反馈使用后强度 5 →
生成"8 → 5"记录 → 在"我的 EchoMind"查看历史与趋势图。

## 六、知识产权声明

本项目全部代码、数据库结构、设计稿、音频文件、部署配置等成果的
知识产权归 **Resomind 团队（项目负责人：李昕融）** 所有。
未经授权，任何单位或个人不得复制、传播或用于商业用途。

特别说明：MVP 中的 10 首音乐均为程序合成（tools/gen_music.py），
不存在任何版权争议，可自由使用于比赛演示与用户测试。
