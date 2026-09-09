# -*- coding: utf-8 -*-
"""K 线 × 事件叙事一致性测试（方案A：事件年方向冲击项）。

用与前端逐位一致的 database/kline.build_candles 重算全部标的年 K，断言：
  1. bull 事件年必须收阳、bear 必须收阴（前端时间轴红绿与利好利空一致）；
  2. kline.js 与 kline.py 的 eventBumps 冲击系数完全一致；
  3. 数据库与种子源一致的关键锚点抽查（靖康/三藩/土木堡崩盘年落位）。
"""
import json
import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.kline import build_candles, next_year  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "database", "dynasty.db")
KLINE_JS = os.path.join(ROOT, "kline.js")

# 各标的（dynasties + figures）统一取数
SQL = {
    "dynasties": dict(
        meta="SELECT * FROM dynasties",
        events=("SELECT year,title,dir,mag FROM events "
                "WHERE dynasty_id=:id ORDER BY year,sort"),
        anchors="SELECT year,value FROM anchors WHERE dynasty_id=:id ORDER BY sort",
        eid="dynasty_id",
    ),
    "figures": dict(
        meta="SELECT * FROM figures",
        events=("SELECT year,title,dir,mag FROM figure_events "
                "WHERE figure_id=:id ORDER BY year,sort"),
        anchors="SELECT year,value FROM figure_anchors WHERE figure_id=:id ORDER BY sort",
        eid="figure_id",
    ),
}


def iter_targets(conn, table):
    cfg = SQL[table]
    for row in conn.execute(cfg["meta"]):
        d = dict(row)
        d["_events"] = [dict(r) for r in conn.execute(
            cfg["events"], {"id": row["id"]})]
        d["_anchors"] = [(r["year"], r["value"]) for r in conn.execute(
            cfg["anchors"], {"id": row["id"]})]
        yield d


def single_year_impacts(dyn):
    """重建年 K，返回 {event_year: (dir, impact_pct)}（bull/bear 事件）。"""
    years, candles = build_candles(
        dyn["start_year"], dyn["end_year"], dyn["peak_year"], dyn["seed"],
        dyn["_anchors"], dyn["_events"])
    closes = {int(y): k[1] for y, k in zip(years, candles)}
    out = {}
    for ev in dyn["_events"]:
        if ev["dir"] not in ("bull", "bear"):
            continue
        y = int(ev["year"])
        prev = -1 if y == 1 else y - 1
        b, c0 = closes.get(prev), closes.get(y)
        if b is None or c0 is None:
            continue
        out[y] = (ev["dir"], ev["title"], (c0 - b) / b * 100)
    return out


@pytest.mark.parametrize("table", list(SQL))
def test_event_direction_matches_candle(table):
    """利好事件年收阳、利空事件年收阴 —— 时间轴红绿不许颠倒。"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    for dyn in iter_targets(conn, table):
        if not dyn["_anchors"]:
            continue
        impacts = single_year_impacts(dyn)
        for y, (d, title, imp) in impacts.items():
            if d == "bull":
                assert imp > 0.2, (
                    f"{dyn['code']} 事件 {y}「{title}」利好收阴 {imp:+.1f}%")
            else:
                assert imp < -0.2, (
                    f"{dyn['code']} 事件 {y}「{title}」利空收阳 {imp:+.1f}%")


def test_kline_js_and_py_share_event_coef():
    """前后端唯一算法源：kline.js 与 kline.py 的事件冲击系数必须逐位一致。"""
    with open(KLINE_JS, encoding="utf-8") as f:
        js = f.read()
    from database.kline import EVENT_COEF, MAG_RANK
    js_coef = json.loads(re.search(r"var EVENT_COEF = (\{[^}]+\});", js).group(1)
                         .replace("'", '"'))
    js_rank = json.loads(re.search(r"var MAG_RANK = (\{[^}]+\});", js).group(1)
                         .replace("'", '"'))
    assert js_coef == EVENT_COEF
    assert {k: int(v) for k, v in js_rank.items()} == MAG_RANK
    # 冲击下限必须压过噪声上限（否则 bear 事件仍可能被噪声托成阳线）
    assert min(EVENT_COEF.values()) > 0.015


def test_famous_crash_years_aligned():
    """史实级崩盘年抽查：崩盘必须发生在事件当年（而非提前/推后）。"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    checks = {
        "DASONG.960": {1127: (-60.0, -45.0)},   # 靖康之变：单年闪崩
        "QING.1644": {1673: (-30.0, -15.0)},    # 三藩之乱
        "MING.1368": {1449: (-58.0, -43.0)},    # 土木堡之变
        "TANG.618": {875: (-50.0, -37.0)},      # 黄巢起义
    }
    for dyn in iter_targets(conn, "dynasties"):
        if dyn["code"] not in checks:
            continue
        years, candles = build_candles(
            dyn["start_year"], dyn["end_year"], dyn["peak_year"], dyn["seed"],
            dyn["_anchors"], dyn["_events"])
        closes = {int(y): k[1] for y, k in zip(years, candles)}
        for y, (lo, hi) in checks[dyn["code"]].items():
            prev = -1 if y == 1 else y - 1
            imp = (closes[y] - closes[prev]) / closes[prev] * 100
            assert lo < imp < hi, (
                f"{dyn['code']} {y} 年冲击 {imp:+.1f}% 不在预期区间 ({lo},{hi})")
