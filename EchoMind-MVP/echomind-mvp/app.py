#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EchoMind MVP 后端
=================
技术栈：Flask + SQLite（stdlib sqlite3）+ 纯静态前端。

数据表：
  users    用户（id TEXT 主键，localStorage 生成的 UUID）
  tracks   曲目库（含 BPM / 节奏 / 刺激度 / 音色 / 情绪标签 / 场景标签 / 推荐阶段）
  sessions 使用会话（含情绪/强度/场景/目标/推荐方案快照/前后评分/时长）
  events   播放行为打点（play / pause / skip / complete）

管理后台鉴权：请求头 X-Admin-Key 或 ?key=，密钥来自环境变量 ADMIN_KEY，
默认值为 echomind2026（演示用，生产请务必修改）。
"""

import csv
import io
import json
import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from recommender import recommend

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "echomind.db"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "echomind2026")

app = Flask(__name__, static_folder="static", static_url_path="/static")

# 事件动作白名单
EVENT_ACTIONS = {"play", "pause", "skip", "complete"}


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    nickname   TEXT
);
CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    file         TEXT NOT NULL,          -- 相对 static/ 的音频路径，如 audio/track01.wav
    cover        TEXT NOT NULL,          -- 相对 static/ 的封面路径，如 covers/cover01.png
    bpm          INTEGER,
    rhythm_type  TEXT,
    stimulation  TEXT,                   -- 低 / 中低
    timbre       TEXT,
    has_vocal    INTEGER DEFAULT 0,
    emotion_tags TEXT,                   -- JSON 数组
    scene_tags   TEXT,                   -- JSON 数组
    stage        TEXT,                   -- 释放 / 稳定 / 放松 / 专注 / 能量
    enabled      INTEGER DEFAULT 1,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    emotion          TEXT NOT NULL,      -- 当前情绪
    intensity_before INTEGER NOT NULL,  -- 使用前强度 1-10
    scene            TEXT NOT NULL,      -- 使用场景
    goal             TEXT NOT NULL,      -- 目标状态
    plan_json        TEXT NOT NULL,      -- 推荐方案快照（JSON）
    intensity_after  INTEGER,           -- 使用后强度 1-10
    duration_sec     REAL,               -- 使用时长（秒）
    completed        INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    track_id    INTEGER,
    action      TEXT NOT NULL,           -- play / pause / skip / complete
    position_sec REAL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
"""


def get_db():
    """获取 SQLite 连接（行对象可按列名访问）。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表（幂等）。"""
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def row_to_track(row, with_url=True):
    """DB 行 -> 曲目 dict（含 JSON 标签解析）。"""
    t = dict(row)
    t["emotion_tags"] = json.loads(t["emotion_tags"] or "[]")
    t["scene_tags"] = json.loads(t["scene_tags"] or "[]")
    t["has_vocal"] = bool(t["has_vocal"])
    t["enabled"] = bool(t["enabled"])
    if with_url:
        t["file_url"] = "/static/" + t["file"]
        t["cover_url"] = "/static/" + t["cover"]
    return t


def seed_tracks():
    """从 tools/tracks.json 初始化曲目库（表空时才写入）。"""
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) AS c FROM tracks").fetchone()["c"]
    if n > 0:
        conn.close()
        return 0
    meta_path = BASE_DIR / "tools" / "tracks.json"
    tracks = json.loads(meta_path.read_text(encoding="utf-8"))
    now = datetime.now().isoformat(timespec="seconds")
    for t in tracks:
        conn.execute(
            """INSERT INTO tracks
               (id, title, file, cover, bpm, rhythm_type, stimulation, timbre,
                has_vocal, emotion_tags, scene_tags, stage, enabled, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t["id"], t["title"], t["file"], t["cover"], t.get("bpm"),
             t.get("rhythm_type"), t.get("stimulation"), t.get("timbre"),
             1 if t.get("has_vocal") else 0,
             json.dumps(t.get("emotion_tags", []), ensure_ascii=False),
             json.dumps(t.get("scene_tags", []), ensure_ascii=False),
             t.get("stage"), 1 if t.get("enabled", True) else 0, now),
        )
    conn.commit()
    conn.close()
    return len(tracks)


def require_admin(f):
    """管理后台鉴权装饰器：X-Admin-Key 请求头或 ?key= 查询参数。"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Admin-Key") or request.args.get("key")
        if key != ADMIN_KEY:
            return jsonify({"error": "unauthorized（管理密钥不正确）"}), 401
        return f(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/admin")
def admin_page():
    return send_from_directory(app.static_folder, "admin.html")


# ---------------------------------------------------------------------------
# 用户 API
# ---------------------------------------------------------------------------
@app.route("/api/session/start", methods=["POST"])
def session_start():
    """开始一次情绪调节：建会话 + 生成三阶段音乐方案。"""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    emotion = data.get("emotion")
    intensity = data.get("intensity_before")
    scene = data.get("scene")
    goal = data.get("goal")
    if not all([user_id, emotion, intensity, scene, goal]):
        return jsonify({"error": "缺少必要参数：user_id/emotion/intensity_before/scene/goal"}), 400
    try:
        intensity = int(intensity)
    except (TypeError, ValueError):
        return jsonify({"error": "intensity_before 须为 1-10 的整数"}), 400
    if not 1 <= intensity <= 10:
        return jsonify({"error": "intensity_before 须为 1-10 的整数"}), 400

    conn = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    # 用户不存在则创建（幂等）
    conn.execute(
        "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, ?)",
        (user_id, now),
    )
    tracks = [row_to_track(r) for r in conn.execute(
        "SELECT * FROM tracks WHERE enabled = 1 ORDER BY id").fetchall()]
    try:
        result = recommend(emotion, intensity, scene, goal, tracks)
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 400

    session_id = uuid.uuid4().hex
    plan_json = json.dumps(result, ensure_ascii=False)
    conn.execute(
        """INSERT INTO sessions
           (id, user_id, created_at, emotion, intensity_before, scene, goal, plan_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        (session_id, user_id, now, emotion, intensity, scene, goal, plan_json),
    )
    conn.commit()
    conn.close()

    plan = json.loads(plan_json)
    return jsonify({
        "session_id": session_id,
        "plan": plan,
    })


@app.route("/api/session/<session_id>/event", methods=["POST"])
def session_event(session_id):
    """播放行为打点：play / pause / skip / complete。"""
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action")
    if action not in EVENT_ACTIONS:
        return jsonify({"error": f"action 须为 {sorted(EVENT_ACTIONS)} 之一"}), 400
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM sessions WHERE id = ?",
                          (session_id,)).fetchone()
    if not exists:
        conn.close()
        return jsonify({"error": "会话不存在"}), 404
    conn.execute(
        """INSERT INTO events (session_id, track_id, action, position_sec, created_at)
           VALUES (?,?,?,?,?)""",
        (session_id, data.get("track_id"),
         action, float(data.get("position_sec") or 0),
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/session/<session_id>/finish", methods=["POST"])
def session_finish(session_id):
    """使用结束：提交使用后强度 + 使用时长，生成前后对比。"""
    data = request.get_json(force=True, silent=True) or {}
    try:
        after = int(data.get("intensity_after"))
    except (TypeError, ValueError):
        return jsonify({"error": "intensity_after 须为 1-10 的整数"}), 400
    if not 1 <= after <= 10:
        return jsonify({"error": "intensity_after 须为 1-10 的整数"}), 400
    duration = data.get("duration_sec")

    conn = get_db()
    row = conn.execute("SELECT intensity_before FROM sessions WHERE id = ?",
                       (session_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "会话不存在"}), 404
    conn.execute(
        """UPDATE sessions SET intensity_after = ?, duration_sec = ?, completed = 1
           WHERE id = ?""",
        (after, float(duration) if duration is not None else None, session_id),
    )
    conn.commit()
    conn.close()
    before = row["intensity_before"]
    return jsonify({
        "ok": True,
        "intensity_before": before,
        "intensity_after": after,
        "delta": before - after,  # 正数表示主观强度下降
    })


@app.route("/api/history")
def history():
    """某用户的历史使用记录（含每段前后评分与时长）。"""
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "缺少 user_id"}), 400
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)).fetchall()
    conn.close()
    items = []
    for r in rows:
        d = dict(r)
        d["plan"] = json.loads(d.pop("plan_json"))
        d["completed"] = bool(d["completed"])
        items.append(d)
    return jsonify({"user_id": user_id, "sessions": items})


@app.route("/api/tracks")
def list_tracks():
    """启用的曲目列表（前端播放用）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tracks WHERE enabled = 1 ORDER BY id").fetchall()
    conn.close()
    return jsonify({"tracks": [row_to_track(r) for r in rows]})


# ---------------------------------------------------------------------------
# 管理后台 API
# ---------------------------------------------------------------------------
@app.route("/api/admin/stats")
@require_admin
def admin_stats():
    """数据总览：用户数 / 使用次数 / 情绪与场景分布 / 前后平均分 / 分场景变化 / 分曲目播放。"""
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    sessions = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
    completed = conn.execute(
        "SELECT COUNT(*) AS c FROM sessions WHERE completed = 1").fetchone()["c"]

    def dist(col):
        rows = conn.execute(
            f"SELECT {col} AS k, COUNT(*) AS c FROM sessions GROUP BY {col}").fetchall()
        return {r["k"]: r["c"] for r in rows}

    avg = conn.execute(
        """SELECT AVG(intensity_before) AS b, AVG(intensity_after) AS a
           FROM sessions WHERE completed = 1
           AND intensity_before IS NOT NULL AND intensity_after IS NOT NULL"""
    ).fetchone()

    scene_rows = conn.execute(
        """SELECT scene, COUNT(*) AS n,
                  AVG(intensity_before) AS b, AVG(intensity_after) AS a,
                  AVG(intensity_before - intensity_after) AS d
           FROM sessions WHERE completed = 1
           AND intensity_before IS NOT NULL AND intensity_after IS NOT NULL
           GROUP BY scene"""
    ).fetchall()

    track_rows = conn.execute(
        """SELECT t.id, t.title, t.stage,
                  SUM(CASE WHEN e.action = 'play' THEN 1 ELSE 0 END) AS plays,
                  SUM(CASE WHEN e.action = 'complete' THEN 1 ELSE 0 END) AS completes,
                  SUM(CASE WHEN e.action = 'skip' THEN 1 ELSE 0 END) AS skips
           FROM tracks t LEFT JOIN events e ON e.track_id = t.id
           GROUP BY t.id ORDER BY t.id"""
    ).fetchall()

    emotion_dist = dist("emotion")
    scene_dist = dist("scene")
    conn.close()

    return jsonify({
        "users": users,
        "sessions": sessions,
        "completed_sessions": completed,
        "emotion_dist": emotion_dist,
        "scene_dist": scene_dist,
        "avg_before": round(avg["b"], 2) if avg["b"] is not None else None,
        "avg_after": round(avg["a"], 2) if avg["a"] is not None else None,
        "scene_feedback": [
            {"scene": r["scene"], "count": r["n"],
             "avg_before": round(r["b"], 2), "avg_after": round(r["a"], 2),
             "avg_delta": round(r["d"], 2)}
            for r in scene_rows
        ],
        "track_plays": [dict(r) for r in track_rows],
    })


@app.route("/api/admin/tracks", methods=["GET", "POST"])
@require_admin
def admin_tracks():
    conn = get_db()
    if request.method == "GET":
        rows = conn.execute("SELECT * FROM tracks ORDER BY id").fetchall()
        conn.close()
        return jsonify({"tracks": [row_to_track(r) for r in rows]})

    # POST：新增曲目
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("title"):
        conn.close()
        return jsonify({"error": "缺少 title"}), 400
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO tracks
           (title, file, cover, bpm, rhythm_type, stimulation, timbre,
            has_vocal, emotion_tags, scene_tags, stage, enabled, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (data.get("title"), data.get("file", ""), data.get("cover", ""),
         data.get("bpm"), data.get("rhythm_type"), data.get("stimulation"),
         data.get("timbre"), 1 if data.get("has_vocal") else 0,
         json.dumps(data.get("emotion_tags", []), ensure_ascii=False),
         json.dumps(data.get("scene_tags", []), ensure_ascii=False),
         data.get("stage", "放松"),
         1 if data.get("enabled", True) else 0, now),
    )
    track_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM tracks WHERE id = ?",
                       (track_id,)).fetchone()
    conn.close()
    return jsonify({"track": row_to_track(row)}), 201


@app.route("/api/admin/tracks/<int:track_id>", methods=["PUT", "DELETE"])
@require_admin
def admin_track_item(track_id):
    conn = get_db()
    if request.method == "DELETE":
        cur = conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            return jsonify({"error": "曲目不存在"}), 404
        return jsonify({"ok": True})

    # PUT：修改曲目及标签
    data = request.get_json(force=True, silent=True) or {}
    fields = ("title", "file", "cover", "bpm", "rhythm_type", "stimulation",
              "timbre", "has_vocal", "emotion_tags", "scene_tags", "stage",
              "enabled")
    sets, vals = [], []
    for f in fields:
        if f in data:
            v = data[f]
            if f in ("emotion_tags", "scene_tags"):
                v = json.dumps(v or [], ensure_ascii=False)
            elif f in ("has_vocal", "enabled"):
                v = 1 if v else 0
            sets.append(f"{f} = ?")
            vals.append(v)
    if not sets:
        conn.close()
        return jsonify({"error": "没有可更新的字段"}), 400
    vals.append(track_id)
    cur = conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE id = ?",
                       vals)
    conn.commit()
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"error": "曲目不存在"}), 404
    row = conn.execute("SELECT * FROM tracks WHERE id = ?",
                       (track_id,)).fetchone()
    conn.close()
    return jsonify({"track": row_to_track(row)})


@app.route("/api/admin/sessions")
@require_admin
def admin_sessions():
    """会话明细（含每会话的打点次数）。"""
    conn = get_db()
    rows = conn.execute(
        """SELECT s.*, COUNT(e.id) AS event_count
           FROM sessions s LEFT JOIN events e ON e.session_id = s.id
           GROUP BY s.id ORDER BY s.created_at DESC LIMIT 500"""
    ).fetchall()
    conn.close()
    items = []
    for r in rows:
        d = dict(r)
        d["completed"] = bool(d["completed"])
        d["plan_titles"] = [s["track"]["title"]
                            for s in json.loads(d.pop("plan_json"))["stages"]]
        items.append(d)
    return jsonify({"sessions": items})


@app.route("/api/admin/export.csv")
@require_admin
def admin_export():
    """导出全部会话 + 事件汇总数据（CSV，UTF-8 BOM，Excel 可直接打开）。"""
    conn = get_db()
    rows = conn.execute(
        """SELECT s.*,
                  SUM(CASE WHEN e.action = 'play' THEN 1 ELSE 0 END) AS n_play,
                  SUM(CASE WHEN e.action = 'skip' THEN 1 ELSE 0 END) AS n_skip,
                  SUM(CASE WHEN e.action = 'complete' THEN 1 ELSE 0 END) AS n_complete
           FROM sessions s LEFT JOIN events e ON e.session_id = s.id
           GROUP BY s.id ORDER BY s.created_at"""
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["会话ID", "用户ID", "开始时间", "当前情绪", "使用前强度(1-10)",
                "使用场景", "目标状态", "推荐曲目", "使用后强度(1-10)",
                "主观强度变化(前-后)", "使用时长(秒)", "是否完成",
                "播放次数", "跳过次数", "播完次数"])
    for r in rows:
        d = dict(r)
        titles = " → ".join(s["track"]["title"]
                            for s in json.loads(d["plan_json"])["stages"])
        before, after = d["intensity_before"], d["intensity_after"]
        delta = (before - after) if after is not None else ""
        w.writerow([d["id"], d["user_id"], d["created_at"], d["emotion"],
                    before, d["scene"], d["goal"], titles, after if after is not None else "",
                    delta, d["duration_sec"] if d["duration_sec"] is not None else "",
                    "是" if d["completed"] else "否",
                    d["n_play"] or 0, d["n_skip"] or 0, d["n_complete"] or 0])
    data = "\ufeff" + buf.getvalue()  # BOM，Excel 中文不乱码
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename=echomind_sessions.csv"},
    )


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    n = seed_tracks()
    if n:
        print(f"[EchoMind] 已初始化 {n} 首曲目")
    port = int(os.environ.get("PORT", 5000))
    print(f"[EchoMind] 服务启动：http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
