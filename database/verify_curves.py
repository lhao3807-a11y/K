# -*- coding: utf-8 -*-
"""
国运 / 气运曲线校验器
======================
用与前端 index.html、figure.html **完全一致** 的算法（锚点 smoothstep 插值 +
mulberry32 噪声 + 见顶年 1.07 冲高）重算每个标的的 K 线，逐项校验：

  1. 年份序列跳过 0 年（公元前 1 年之后是公元 1 年）
  2. 无 NaN / 无负数 / high-low 合法
  3. 历史最高点落在 peak_year（金色 pin 与标志性事件同年）
  4. 皇帝 K / 人生阶段 K 的红绿（起价 vs 终价）与区间聚合正确
  5. 终局收盘接近退市价（锚点末值）

算法实现统一在 database/kline.py —— 本文件不再自带算法，王朝与人物共用同一份。

用法：
    python database/verify_curves.py            # 校验所有王朝 + 人物
    python database/verify_curves.py --db PATH
"""
import argparse
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dynasty.db")

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from kline import (  # noqa: E402 —— 需先补 sys.path
    build_candles, aggregate, year_range, round1,
)


def build(dyn, anchors, emperors, events=None):
    """兼容旧签名：返回 (years, candles, emp_candles)。"""
    years, candles = build_candles(
        dyn["start_year"], dyn["end_year"], dyn["peak_year"], dyn["seed"],
        anchors, events)
    spans = [(em["start_year"], em["end_year"]) for em in emperors]
    return years, candles, aggregate(candles, years, spans)


def check_events(years, candles, events, label):
    """事件红绿一致性：bull 事件年须收阳、bear 须收阴（single-year vs 前一年）。"""
    errs = []
    closes = {int(y): k[1] for y, k in zip(years, candles)}

    def prev_year(y):
        return -1 if y == 1 else y - 1

    for ev in events or []:
        y = int(ev["year"])
        d = ev["dir"]
        if d not in ("bull", "bear"):
            continue
        b, c0 = closes.get(prev_year(y)), closes.get(y)
        if b is None or c0 is None:
            continue
        imp = (c0 - b) / b * 100
        if d == "bull" and imp < -0.2:
            errs.append(f"{label} 事件 {y}「{ev['title']}」利好收阴 {imp:+.1f}%")
        elif d == "bear" and imp > 0.2:
            errs.append(f"{label} 事件 {y}「{ev['title']}」利空收阳 {imp:+.1f}%")
    return errs


def check_candles(years, candles, peak, label):
    """K 线序列的通用校验，返回 errors。"""
    errs = []
    if "0" in years:
        errs.append(f"{label} 年份序列含 0 年（纪年错误）")

    for i, k in enumerate(candles):
        if any(v is None or v != v for v in k):          # NaN
            errs.append(f"{label} 第 {i} 根 K 线含 NaN")
            break
        if k[3] < max(k[0], k[1]) - 1e-9 or k[2] > min(k[0], k[1]) + 1e-9:
            errs.append(f"{label} 第 {i} 根 K 线高低价非法 {k}")
            break
        if k[2] <= 0:
            errs.append(f"{label} 第 {i} 根 K 线最低价 <= 0（{k[2]}）")
            break

    hi_i = max(range(len(candles)), key=lambda i: candles[i][3])
    hi_year = int(years[hi_i])
    if peak is not None and hi_year != peak:
        errs.append(f"{label} 历史最高落在 {hi_year}（{candles[hi_i][3]}），"
                    f"但 peak_year={peak}")
    return errs


def check(dyn, anchors, emperors, events=None):
    """王朝校验，返回 (errors, info)。"""
    years, candles, emp = build(dyn, anchors, emperors, events)
    errs = check_candles(years, candles, dyn["peak_year"], dyn["code"])
    errs += check_events(years, candles, events, dyn["code"])
    hi_i = max(range(len(candles)), key=lambda i: candles[i][3])
    return errs, {
        "bars": len(candles),
        "high": candles[hi_i][3],
        "high_year": int(years[hi_i]),
        "peak_year": dyn["peak_year"],
        "last": candles[-1][1],
        "emperors": len(emp),
        "reds": sum(1 for e in emp if e[1] >= e[0]),
    }


def check_figure(fig, anchors, periods, events=None):
    """人物校验，返回 (errors, info)。阶段 K 的区间须与 periods 一一对应。"""
    years, candles = build_candles(
        fig["start_year"], fig["end_year"], fig["peak_year"], fig["seed"],
        anchors, events)
    errs = check_candles(years, candles, fig["peak_year"], fig["code"])
    errs += check_events(years, candles, events, fig["code"])

    spans = [(p["start_year"], p["end_year"]) for p in periods]
    per = aggregate(candles, years, spans)

    # 阶段须无缝覆盖标的全区间（与王朝"皇帝无缝覆盖"同规则）
    if periods:
        cur = fig["start_year"]
        for p in periods:
            if p["start_year"] != cur:
                errs.append(f"{fig['code']} 人生阶段断裂：期望 {cur}，"
                            f"实际 {p['name']}={p['start_year']}")
                break
            cur = p["end_year"] + 1
        if cur - 1 != fig["end_year"]:
            errs.append(f"{fig['code']} 人生阶段未覆盖到 {fig['end_year']}"
                        f"（止于 {cur - 1}）")

    hi_i = max(range(len(candles)), key=lambda i: candles[i][3])
    return errs, {
        "bars": len(candles),
        "high": candles[hi_i][3],
        "high_year": int(years[hi_i]),
        "peak_year": fig["peak_year"],
        "last": candles[-1][1],
        "emperors": len(per),
        "reds": sum(1 for e in per if e[1] >= e[0]),
    }


def _print_table(title, header, rows, err_map):
    print(f"\n== {title} ==")
    print(header)
    print("-" * 63)
    total = 0
    for code, line, errs in rows:
        flag = "" if not errs else "  <== 见下"
        print(f"{line}{flag}")
        for e in errs:
            total += 1
            print(f"    [!] {code}: {e}")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[x] 数据库不存在：{args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    header = (f"{'code':<12}{'根数':>6}{'历史最高':>10}{'@年份':>8}"
              f"{'peak':>8}{'终值':>8}{'分段':>6}{'红K':>5}")

    # ---- 王朝 ----
    dyn_rows = []
    skipped = []
    for d in conn.execute("SELECT * FROM dynasties ORDER BY start_year"):
        anchors = [(r["year"], r["value"]) for r in conn.execute(
            "SELECT year,value FROM anchors WHERE dynasty_id=? ORDER BY sort", (d["id"],))]
        emperors = [r for r in conn.execute(
            "SELECT name,start_year,end_year FROM emperors "
            "WHERE dynasty_id=? ORDER BY sort", (d["id"],))]
        events = [dict(r) for r in conn.execute(
            "SELECT year,title,dir,mag FROM events "
            "WHERE dynasty_id=? ORDER BY year,sort", (d["id"],))]
        if not anchors:
            skipped.append(d["code"])
            continue
        errs, info = check(d, anchors, emperors, events)
        dyn_rows.append((d["code"],
                         f"{d['code']:<12}{info['bars']:>6}{info['high']:>10}"
                         f"{info['high_year']:>8}{str(info['peak_year']):>8}"
                         f"{info['last']:>8}{info['emperors']:>6}{info['reds']:>5}",
                         errs))

    total_err = _print_table("王朝 · 国运指数", header, dyn_rows, None)

    # ---- 人物 ----
    fig_rows = []
    fig_skipped = []
    try:
        figures = conn.execute("SELECT * FROM figures ORDER BY start_year").fetchall()
    except sqlite3.OperationalError:
        figures = []
    for f in figures:
        anchors = [(r["year"], r["value"]) for r in conn.execute(
            "SELECT year,value FROM figure_anchors WHERE figure_id=? ORDER BY sort",
            (f["id"],))]
        periods = [r for r in conn.execute(
            "SELECT name,start_year,end_year FROM figure_periods "
            "WHERE figure_id=? ORDER BY sort", (f["id"],))]
        events = [dict(r) for r in conn.execute(
            "SELECT year,title,dir,mag FROM figure_events "
            "WHERE figure_id=? ORDER BY year,sort", (f["id"],))]
        if not anchors:
            fig_skipped.append(f["code"])
            continue
        errs, info = check_figure(f, anchors, periods, events)
        fig_rows.append((f["code"],
                         f"{f['code']:<12}{info['bars']:>6}{info['high']:>10}"
                         f"{info['high_year']:>8}{str(info['peak_year']):>8}"
                         f"{info['last']:>8}{info['emperors']:>6}{info['reds']:>5}",
                         errs))

    if figures:
        total_err += _print_table("人物 · 气运指数", header, fig_rows, None)

    print("-" * 63)
    if skipped:
        print(f"跳过（无锚点数据）：{', '.join(skipped)}")
    if fig_skipped:
        print(f"人物跳过（无锚点数据）：{', '.join(fig_skipped)}")
    if total_err:
        print(f"[x] 共 {total_err} 项校验失败")
        sys.exit(1)
    print("[ok] 全部标的曲线校验通过")
    conn.close()


if __name__ == "__main__":
    main()
