# -*- coding: utf-8 -*-
"""
K 线引擎（王朝国运 / 人物气运 共用）
====================================
本模块是**唯一**的 K 线算法实现，王朝与人物两个板块都必须调用它，
严禁各自复制一份 —— 首页迷你图、盘面页主图、校验器三处数字对不上，
历史上就是算法分叉造成的。

算法与前端 JS 逐位一致，任何改动都必须同步前端：
    - 开普勒：open = 首年取锚点首值，其余取上一年 close（**未取整**）
    - close = 锚点 smoothstep 插值 × (1 ± 1.5% 噪声) × (见顶年 ×1.07) × (1 + 事件冲击)
    - 事件冲击：bull +档位 / bear -档位 / vol 当年+半档次年-半档（巨6% 大4% 中2.5% 小2%）
    - high/low = open/close 的极值（故影线不外扩，K 线为"光头光脚 + 影线"混合）
    - 年份序列跳过 0 年（公元前 1 年之后是公元 1 年）

对外接口：
    build_candles(start, end, peak, seed, anchors, events=None) -> (years, candles)
    event_bumps(events)                                        -> {year: bump}
    aggregate(candles, years, spans)               -> [(open, close, low, high)]
"""
import math

ISSUE_DEFAULT = 100.0
PEAK_BOOST = 1.07      # 见顶年冲高系数
NOISE = 0.03           # 噪声幅度（±1.5%）

# 事件冲击档位系数：保证 bull/bear 事件年单年方向确定（系数下限须 > 噪声上限 1.5%）
MAG_RANK = {"巨": 4, "大": 3, "中": 2, "小": 1}
EVENT_COEF = {"巨": 0.06, "大": 0.04, "中": 0.025, "小": 0.02}


def event_bumps(events):
    """事件表 -> {year: bump}。

    events: 每项含 year/dir/mag（dict-like）或 (year, dir, mag) 三元组。
    同年多事件取档位最高的一条（叙事上"最强驱动"定价当年 K）；
    vol 双向：当年 +半档（情绪驱动），次年 -半档（兑现回落）。
    """
    best = {}
    for ev in events or []:
        if isinstance(ev, dict):
            y, d, mag = int(ev["year"]), ev["dir"], ev["mag"] or ""
        else:
            y, d, mag = int(ev[0]), ev[1], ev[2] or ""
        rank = MAG_RANK.get(mag[1:], 0)
        cur = best.get(y)
        if cur is None or rank > cur[0]:
            best[y] = (rank, d, mag)
    bumps = {}
    for y, (_rank, d, mag) in best.items():
        c = EVENT_COEF.get(mag[1:], EVENT_COEF["小"])
        if d == "bull":
            bumps[y] = bumps.get(y, 0.0) + c
        elif d == "bear":
            bumps[y] = bumps.get(y, 0.0) - c
        elif d == "vol":
            bumps[y] = bumps.get(y, 0.0) + c / 2
            ny = next_year(y)
            bumps[ny] = bumps.get(ny, 0.0) - c / 2
    return bumps


def mulberry32(a):
    """确定性伪随机（与前端同名函数逐位一致）。"""
    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) | 0) * (1 | t) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) | 0) * (61 | t) & 0xFFFFFFFF)) ^ t & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd


def round1(x):
    """保留一位小数（四舍五入时机与前端一致）。"""
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
    """纪年的下一年（无 0 年：-1 之后是 1）。"""
    return 1 if y == -1 else y + 1


def year_range(s, e):
    """生成 [s, e] 的年份序列，跳过 0 年。"""
    out, y = [], s
    while y <= e:
        out.append(y)
        y = next_year(y)
    return out


def build_candles(start, end, peak, seed, anchors, events=None):
    """生成年 K。

    anchors: [(year, value), ...] 按年份升序
    events:  [(year, dir, mag), ...] 或含 year/dir/mag 的 dict 列表（事件冲击）
    返回 (years, candles)，candles[i] = [open, close, low, high]
    """
    anchors = [(a[0], float(a[1])) for a in anchors]
    rnd = mulberry32(int(seed))
    bumps = event_bumps(events)

    years, candles = [], []
    prev_close = anchors[0][1]
    for y in year_range(start, end):
        years.append(str(y))
        target = interp_on(anchors, y)
        open_ = anchors[0][1] if y == start else prev_close
        close = (target * (1 + (rnd() - 0.5) * NOISE)
                 * (PEAK_BOOST if y == peak else 1)
                 * (1 + bumps.get(y, 0.0)))
        candles.append([round1(open_), round1(close),
                        round1(min(open_, close)), round1(max(open_, close))])
        prev_close = close
    return years, candles


def aggregate(candles, years, spans):
    """把年 K 按区间聚合成大 K（皇帝 K / 人生阶段 K）。

    spans: [(start_year, end_year), ...]
    返回 [(open, close, low, high), ...]，open=区间首年开盘，close=区间末年收盘。
    """
    idx = {y: i for i, y in enumerate(years)}
    out = []
    for s, e in spans:
        hi, lo, o, c = -math.inf, math.inf, 0.0, 0.0
        for y in year_range(s, e):
            k = candles[idx[str(y)]]
            if y == s:
                o = k[0]
            c = k[1]
            hi = max(hi, k[3])
            lo = min(lo, k[2])
        out.append((round1(o), round1(c), round1(lo), round1(hi)))
    return out


def stats(candles, issue=ISSUE_DEFAULT):
    """常用统计：终值、最高、最大回撤、较发行价涨跌幅。"""
    last = candles[-1][1]
    hi = max(k[3] for k in candles)
    running_peak, dd = 0.0, 0.0
    for k in candles:
        running_peak = max(running_peak, k[3])
        dd = min(dd, (k[2] - running_peak) / running_peak * 100)
    return {
        "last": round1(last),
        "high": round1(hi),
        "chg": (last - issue) / issue * 100,
        "max_drawdown": dd,
    }
