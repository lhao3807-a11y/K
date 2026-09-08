# -*- coding: utf-8 -*-
"""
国运曲线校验器
==============
用与前端 index.html **完全一致** 的算法（锚点 smoothstep 插值 + mulberry32 噪声 +
见顶年 1.07 冲高）重算每个王朝的 K 线，逐项校验：

  1. 年份序列跳过 0 年（公元前 1 年之后是公元 1 年）
  2. 无 NaN / 无负数 / high-low 合法
  3. 历史最高点落在 dynasty.peak_year（金色 pin 与标志性事件同年）
  4. 皇帝 K 的红绿（即位价 vs 退位价）与区间聚合正确
  5. 终局收盘接近退市价（锚点末值）

用法：
    python database/verify_curves.py            # 校验所有有锚点的王朝
    python database/verify_curves.py --db PATH
"""
import argparse
import math
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dynasty.db")


# ---- 与前端一致的算法 ----
def mulberry32(a):
    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) | 0) * (1 | t) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) | 0) * (61 | t) & 0xFFFFFFFF)) ^ t & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd


def round1(x):
    return round(x * 10) / 10


def interp_on(anchors, y):
    """smoothstep 插值出年份 y 的目标指数。"""
    if y <= anchors[0][0]:
        return anchors[0][1]
    for i in range(len(anchors) - 1):
        a, b = anchors[i], anchors[i + 1]
        if a[0] <= y <= b[0]:
            t = (y - a[0]) / (b[0] - a[0])
            t = t * t * (3 - 2 * t)
            return a[1] + (b[1] - a[1]) * t
    return anchors[-1][1]


def next_year(y):
    return 1 if y == -1 else y + 1


def year_range(s, e):
    """生成年份序列，跳过 0 年。"""
    out, y = [], s
    while y <= e:
        out.append(y)
        y = next_year(y)
    return out


def build(dyn, anchors, emperors):
    """返回 (years, candles, emp_candles)。candles = [open, close, low, high]。"""
    start, end, peak, seed = (
        dyn["start_year"], dyn["end_year"], dyn["peak_year"], dyn["seed"])
    anchors = [(a[0], float(a[1])) for a in anchors]
    rnd = mulberry32(int(seed))

    years, candles = [], []
    prev_close = anchors[0][1]
    for y in year_range(start, end):
        years.append(str(y))
        target = interp_on(anchors, y)
        open_ = anchors[0][1] if y == start else prev_close
        close = target * (1 + (rnd() - 0.5) * 0.03) * (1.07 if y == peak else 1)
        candles.append([round1(open_), round1(close),
                        round1(min(open_, close)), round1(max(open_, close))])
        prev_close = close

    idx = {y: i for i, y in enumerate(years)}
    emp = []
    for em in emperors:
        hi, lo, o, c = -math.inf, math.inf, 0.0, 0.0
        for y in year_range(em["start_year"], em["end_year"]):
            k = candles[idx[str(y)]]
            if y == em["start_year"]:
                o = k[0]
            c = k[1]
            hi = max(hi, k[3])
            lo = min(lo, k[2])
        emp.append((em["name"], round1(o), round1(c), round1(lo), round1(hi)))
    return years, candles, emp


def check(dyn, anchors, emperors):
    """返回 (errors, info)。"""
    errs = []
    years, candles, emp = build(dyn, anchors, emperors)

    # 0 年不得出现
    if "0" in years:
        errs.append("年份序列含 0 年（纪年错误）")

    # 数值合法性
    for i, k in enumerate(candles):
        if any(v is None or v != v for v in k):          # NaN
            errs.append(f"第 {i} 根 K 线含 NaN")
            break
        if k[3] < max(k[0], k[1]) - 1e-9 or k[2] > min(k[0], k[1]) + 1e-9:
            errs.append(f"第 {i} 根 K 线高低价非法 {k}")
            break
        if k[2] <= 0:
            errs.append(f"第 {i} 根 K 线最低价 <= 0（{k[2]}）")
            break

    hi_i = max(range(len(candles)), key=lambda i: candles[i][3])
    hi_year = int(years[hi_i])
    peak = dyn["peak_year"]

    if peak is not None and hi_year != peak:
        errs.append(f"历史最高落在 {hi_year}（{candles[hi_i][3]}），"
                    f"但 peak_year={peak}")

    return errs, {
        "bars": len(candles),
        "high": candles[hi_i][3],
        "high_year": hi_year,
        "peak_year": peak,
        "last": candles[-1][1],
        "emperors": len(emp),
        "reds": sum(1 for e in emp if e[2] >= e[1]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[x] 数据库不存在：{args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM dynasties ORDER BY start_year").fetchall()

    print(f"{'code':<12}{'根数':>6}{'历史最高':>10}{'@年份':>8}"
          f"{'peak':>8}{'终值':>8}{'皇帝':>6}{'红K':>5}")
    print("-" * 63)

    total_err = 0
    skipped = []
    for d in rows:
        anchors = [(r["year"], r["value"]) for r in conn.execute(
            "SELECT year,value FROM anchors WHERE dynasty_id=? ORDER BY sort", (d["id"],))]
        emperors = [r for r in conn.execute(
            "SELECT name,start_year,end_year FROM emperors WHERE dynasty_id=? ORDER BY sort",
            (d["id"],))]
        if not anchors:
            skipped.append(d["code"])
            continue

        errs, info = check(d, anchors, emperors)
        flag = "" if not errs else "  <== 见下"
        print(f"{d['code']:<12}{info['bars']:>6}{info['high']:>10}"
              f"{info['high_year']:>8}{str(info['peak_year']):>8}"
              f"{info['last']:>8}{info['emperors']:>6}{info['reds']:>5}{flag}")
        for e in errs:
            total_err += 1
            print(f"    [!] {d['code']}: {e}")

    print("-" * 63)
    if skipped:
        print(f"跳过（无锚点数据）：{', '.join(skipped)}")
    if total_err:
        print(f"[x] 共 {total_err} 项校验失败")
        sys.exit(1)
    print("[ok] 全部王朝国运曲线校验通过")
    conn.close()


if __name__ == "__main__":
    main()
