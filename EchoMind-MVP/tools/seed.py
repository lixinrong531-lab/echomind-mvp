#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EchoMind 数据库初始化脚本
--------------------------
用法：python tools/seed.py
功能：建表 + 从 tools/tracks.json 写入 10 首种子曲目（表空时才写入，可重复执行）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import init_db, seed_tracks  # noqa: E402

if __name__ == "__main__":
    init_db()
    n = seed_tracks()
    if n:
        print(f"[seed] 已写入 {n} 首曲目")
    else:
        print("[seed] 曲目表已有数据，未重复写入")
