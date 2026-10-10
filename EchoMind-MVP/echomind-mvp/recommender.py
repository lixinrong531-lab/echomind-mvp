#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EchoMind 推荐引擎（规则 + 标签匹配）
------------------------------------
第一版 MVP 不使用复杂 AI 模型，采用可解释的规则推荐：

1. 目标状态 -> 三阶段调节路径（固定映射）
2. 每个阶段按阶段过滤曲目，优先选择场景标签命中当前场景的曲目，
   命中"通用"标签的曲目作为兜底
3. 同一 session 内三首曲目不重复
4. 场景标签经过调校：例如"考试前"与"演出前"在"释放"阶段会命中
   不同曲目（晨雾释放 vs 潮汐释放），体现"同一种情绪在不同场景下
   音乐需求不同"的核心创新点
5. 生成可解释的推荐文案，全站严禁医疗承诺：
   不许出现"治疗/疗效/保证降低心率/检测出焦虑症"等表述，
   效果一律描述为"主观感受变化"。
"""

import hashlib

# 目标状态 -> 三阶段路径
GOAL_TO_STAGES = {
    "平静下来": ["释放", "稳定", "放松"],
    "放松": ["稳定", "放松", "放松"],
    "专注": ["稳定", "专注", "稳定"],
    "恢复能量": ["释放", "能量", "稳定"],
    "暂时不想思考": ["放松", "放松", "稳定"],
}

# 目标状态 -> 文案用词（"过渡到更加__的状态"）
GOAL_WORD = {
    "平静下来": "平稳",
    "放松": "放松",
    "专注": "专注",
    "恢复能量": "有能量",
    "暂时不想思考": "放空",
}

# 目标状态 -> 播放页顶部"当前目标"文案
GOAL_TRANSITION = {
    "平静下来": "平稳",
    "放松": "放松",
    "专注": "专注",
    "恢复能量": "有能量",
    "暂时不想思考": "放空",
}

# 每阶段的推荐理由模板
STAGE_REASON = {
    "释放": "先释放：{title}节奏稍明亮、拨弦稍密，帮你把紧绷的情绪先松开一个口。",
    "稳定": "再稳定：{title}以约 60bpm 的柔和低音脉动陪伴，配合稀疏拨弦，让呼吸和心绪慢慢落定。",
    "放松": "后放松：{title}极稀疏的铺底与空灵泛音，低刺激，陪你沉入更松弛的状态。",
    "专注": "再专注：{title}极简铺底与高频稀疏点缀，低干扰，帮你把注意力轻轻收回来。",
    "能量": "再充能：{title}明亮铺底叠加温暖低音脉动，温和地把能量提起来。",
}


def _pick_index(key_parts, n):
    """确定性 tie-break：同一输入永远选同一首，不同场景可能选不同首。"""
    h = hashlib.md5("|".join(key_parts).encode("utf-8")).hexdigest()
    return int(h, 16) % n


def pick_track(stage, scene, emotion, goal, tracks, used_ids):
    """
    为单个阶段挑选一首曲目。
    tracks: 曲目 dict 列表（含 scene_tags / stage / enabled 等字段）
    返回选中的曲目 dict。
    """
    candidates = [t for t in tracks if t["stage"] == stage and t.get("enabled", True)]
    if not candidates:
        raise ValueError(f"阶段「{stage}」没有可用曲目")

    # 优先场景标签精确命中，其次"通用"兜底
    exact = [t for t in candidates if scene in t["scene_tags"] and scene != "通用"]
    generic = [t for t in candidates if "通用" in t["scene_tags"]]
    pool = exact or generic or candidates

    # 同一 session 内不重复
    pool = [t for t in pool if t["id"] not in used_ids]
    if not pool:  # 极端兜底：放开"通用"限制再找
        pool = [t for t in candidates if t["id"] not in used_ids] or candidates

    pool = sorted(pool, key=lambda t: t["id"])
    if len(pool) == 1:
        return pool[0]
    # 多首并列时，用（场景+情绪+目标+阶段）哈希决定，保证可复现且场景敏感
    return pool[_pick_index([scene, emotion, goal, stage], len(pool))]


def build_explanation(emotion, intensity, scene, goal, stages):
    """生成可解释文案（无医疗承诺）。"""
    path_str = " → ".join(stages)
    goal_word = GOAL_WORD.get(goal, "平稳")
    return (
        f"你当前选择的是「{scene} · {emotion} {intensity}/10」，"
        f"因此我们优先匹配与「{scene}」场景契合、刺激度较低的音乐，"
        f"并通过「{path_str}」三段渐进式内容，"
        f"帮助你从当前状态过渡到更加{goal_word}的状态。"
        f"以上推荐基于你的主观选择生成，仅供日常自我调节参考，不构成任何医疗建议。"
    )


def recommend(emotion, intensity, scene, goal, tracks):
    """
    主入口：根据 用户情绪/强度/场景/目标 生成三阶段音乐方案。
    返回 {"stages": [...], "explanation": "..."}，
    每个 stage 为 {"stage": 阶段名, "track": 曲目dict, "reason": 推荐理由}。
    """
    stages = GOAL_TO_STAGES.get(goal)
    if not stages:
        raise ValueError(f"未知目标状态：{goal}")

    used_ids = set()
    plan = []
    for stage in stages:
        track = pick_track(stage, scene, emotion, goal, tracks, used_ids)
        used_ids.add(track["id"])
        plan.append({
            "stage": stage,
            "track": track,
            "reason": STAGE_REASON[stage].format(title=f"《{track['title']}》"),
        })

    return {
        "stages": plan,
        "explanation": build_explanation(emotion, intensity, scene, goal, stages),
    }


# 简单自检：验证"紧张+考试前"与"紧张+演出前"选出不同曲目
if __name__ == "__main__":
    import json
    from pathlib import Path

    meta = json.loads((Path(__file__).parent / "tools" / "tracks.json").read_text(encoding="utf-8"))
    for sc in ("考试前", "演出前"):
        r = recommend("紧张", 8, sc, "平静下来", meta)
        titles = [s["track"]["title"] for s in r["stages"]]
        print(sc, "->", titles)
