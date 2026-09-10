# -*- coding: utf-8 -*-
"""
人物种子数据导入器
==================
把任意 seed 模块里的人物数据写入 SQLite（已存在则 upsert）。
首次运行会自动执行 schema.sql 建表（CREATE TABLE IF NOT EXISTS，对王朝数据无影响）。

用法：
    python database/import_figure.py                 # 导入全部已知人物
    python database/import_figure.py libai           # 只导入 seed_libai.py
    python database/import_figure.py --list          # 列出可导入模块与人物

校验规则与王朝侧 import_seed.py 对齐（阶段无缝覆盖、事件年份升序、mag 格式、
锚点升序且为正），另加：
  - 每阶段可带 theme（一句话主题）
  - 每事件可带 quote（诗句 / 史料原文佐证），可留空
  - peak_year 须落在 [start_year, end_year]
"""
import argparse
import importlib
import json
import os
import re
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dynasty.db")
SCHEMA = os.path.join(BASE_DIR, "schema.sql")

DIRS = ("bull", "bear", "vol", "neutral")
MAG_RE = re.compile(r"^[+±-][大小中巨]$")

# 模块 -> [(显示名, 常量名), ...]
REGISTRY = {
    "libai": [("李白", "LIBAI")],
    "tang": [("杜甫", "DUFU"), ("王维", "WANGWEI"), ("白居易", "BAIJUYI"),
             ("韩愈", "HANYU"), ("柳宗元", "LIUZONGYUAN")],
    "song": [("苏轼", "SUSHI"), ("王安石", "WANGANSHI"), ("李清照", "LIQINGZHAO"),
             ("岳飞", "YUEFEI"), ("文天祥", "WENTIANXIANG")],
}


def ensure_schema(conn):
    """建表（幂等）。schema.sql 全部为 IF NOT EXISTS，可安全重复执行。"""
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())


def next_year(y):
    """纪年的下一个年份（无 0 年：-1 之后是 1）。"""
    return 1 if y == -1 else y + 1


def validate_figure(name, data):
    """数据自检：阶段无缝覆盖、事件年份升序、mag 格式、锚点升序且为正。"""
    fig, periods, evs, anchors = (
        data["figure"], data["periods"], data["events"], data["anchors"])
    errors = []
    s0, e0 = fig["start_year"], fig["end_year"]
    if s0 > e0:
        errors.append(f"{name} 起始年 {s0} 晚于结束年 {e0}")

    # 人生阶段无缝覆盖（与王朝"皇帝无缝覆盖"同规则）
    cur = s0
    last = None
    for nm, theme, s, e in periods:
        if s > e:
            errors.append(f"{name} 阶段 {nm} 区间非法 {s}>{e}")
        if s != cur:
            errors.append(f"{name} 阶段区间断裂：期望 {cur}，实际 {nm}={s}")
        cur = next_year(e)
        last = e
    if last is not None and cur != next_year(e0):
        errors.append(f"{name} 阶段区间未覆盖到 {e0}（止于 {last}）")

    # 事件：年份合法 + dir/mag 合法 + 年份升序
    prev_y = None
    for ev in evs:
        y, t, term, dr, mag = ev[0], ev[1], ev[2], ev[3], ev[4]
        if not (s0 <= y <= e0):
            errors.append(f"{name} 事件「{t}」年份 {y} 超出 [{s0},{e0}]")
        if dr not in DIRS:
            errors.append(f"{name} 事件「{t}」dir 非法 {dr}")
        if not MAG_RE.match(mag or ""):
            errors.append(f"{name} 事件「{t}」mag 非法 {mag}")
        if prev_y is not None and y < prev_y:
            errors.append(f"{name} 事件年份未升序：「{t}」{y} < 上一条 {prev_y}")
        prev_y = y

    # 锚点：升序 + 年份合法 + 值为正
    prev_a = None
    for y, v in anchors:
        if not (s0 <= y <= e0):
            errors.append(f"{name} 锚点年份 {y} 超出 [{s0},{e0}]")
        if v <= 0:
            errors.append(f"{name} 锚点值 {v} 非法（须为正）")
        if prev_a is not None and y < prev_a:
            errors.append(f"{name} 锚点年份未升序：{y} < 上一个 {prev_a}")
        prev_a = y

    pk = fig.get("peak_year")
    if pk is not None and not (s0 <= pk <= e0):
        errors.append(f"{name} peak_year {pk} 超出 [{s0},{e0}]")

    if not fig.get("code"):
        errors.append(f"{name} 缺少 code")

    return errors


def upsert(conn, name, data):
    fig, periods, evs, anchors = (
        data["figure"], data["periods"], data["events"], data["anchors"])
    code = fig["code"]
    row = conn.execute("SELECT id FROM figures WHERE code=?", (code,)).fetchone()
    fig["updated_at"] = "datetime('now','localtime')"

    if row:
        fid = row[0]
        conn.execute(
            "UPDATE figures SET name=?,alias=?,role=?,range_label=?,start_year=?,"
            "end_year=?,issue_price=?,peak_year=?,seed=?,dynasty_code=?,summary=?,"
            "is_active=?,notes=?,updated_at=datetime('now','localtime') WHERE id=?",
            (fig["name"], fig.get("alias", ""), fig.get("role", ""),
             fig.get("range_label", ""), fig["start_year"], fig["end_year"],
             fig["issue_price"], fig.get("peak_year"), fig["seed"],
             fig.get("dynasty_code", ""), fig.get("summary", ""),
             fig.get("is_active", 0), fig.get("notes", ""), fid))
        conn.execute("DELETE FROM figure_periods WHERE figure_id=?", (fid,))
        conn.execute("DELETE FROM figure_events WHERE figure_id=?", (fid,))
        conn.execute("DELETE FROM figure_anchors WHERE figure_id=?", (fid,))
        print(f"[ok] 已更新 {name}（code={code}）")
    else:
        cur = conn.execute(
            "INSERT INTO figures(code,name,alias,role,range_label,start_year,end_year,"
            "issue_price,peak_year,seed,dynasty_code,summary,is_active,notes) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, fig["name"], fig.get("alias", ""), fig.get("role", ""),
             fig.get("range_label", ""), fig["start_year"], fig["end_year"],
             fig["issue_price"], fig.get("peak_year"), fig["seed"],
             fig.get("dynasty_code", ""), fig.get("summary", ""),
             fig.get("is_active", 0), fig.get("notes", "")))
        fid = cur.lastrowid
        print(f"[ok] 已新增 {name}（code={code}）")

    conn.executemany(
        "INSERT INTO figure_periods(figure_id,name,theme,start_year,end_year,sort) "
        "VALUES(?,?,?,?,?,?)",
        [(fid, nm, theme, s, e, i) for i, (nm, theme, s, e) in enumerate(periods)])
    conn.executemany(
        "INSERT INTO figure_events(figure_id,year,title,term,dir,mag,description,"
        "quote,sort) VALUES(?,?,?,?,?,?,?,?,?)",
        [(fid, ev[0], ev[1], ev[2], ev[3], ev[4], ev[5], ev[6] if len(ev) > 6 else "", i)
         for i, ev in enumerate(evs)])
    conn.executemany(
        "INSERT INTO figure_anchors(figure_id,year,value,sort) VALUES(?,?,?,?)",
        [(fid, y, v, i) for i, (y, v) in enumerate(anchors)])
    print(f"      阶段 {len(periods)} / 事件 {len(evs)} / 锚点 {len(anchors)}")


def export_js(conn, path):
    """导出全部 is_active=1 人物的完整盘面数据为 figure_data.js。

    结构：window.FIGURE_DATA = { "<code>": {figure/periods/events/anchors/...} }
    （浏览器直开的演示回退；figure.html 按 hash 或首个 code 取用）
    """
    rows = conn.execute(
        "SELECT * FROM figures WHERE is_active=1 ORDER BY start_year").fetchall()
    if not rows:
        print("[!] 导出跳过：无 is_active=1 的人物")
        return False
    payload = {}
    for row in rows:
        payload[row["code"]] = {
            "figure": {
                "code": row["code"], "name": row["name"], "alias": row["alias"],
                "role": row["role"], "rangeLabel": row["range_label"],
                "startYear": row["start_year"], "endYear": row["end_year"],
                "issuePrice": row["issue_price"], "peakYear": row["peak_year"],
                "seed": row["seed"], "dynastyCode": row["dynasty_code"],
                "summary": row["summary"],
            },
            "periods": [{"name": r["name"], "theme": r["theme"],
                         "s": r["start_year"], "e": r["end_year"]}
                        for r in conn.execute(
                "SELECT name,theme,start_year,end_year FROM figure_periods "
                "WHERE figure_id=? ORDER BY sort", (row["id"],))],
            "events": [dict(r) for r in conn.execute(
                'SELECT year,title,term,dir,mag,description AS "desc",quote '
                "FROM figure_events WHERE figure_id=? ORDER BY sort, year", (row["id"],))],
            "anchors": [list(r) for r in conn.execute(
                "SELECT year,value FROM figure_anchors WHERE figure_id=? "
                "ORDER BY sort, year", (row["id"],))],
            "config": {},
        }
    with open(path, "w", encoding="utf-8") as f:
        f.write("// 自动生成：python database/import_figure.py --export（数据源 database/dynasty.db）\n")
        f.write("// 请勿手改本文件，修改请编辑数据库后重新导入\n")
        f.write("window.FIGURE_DATA = ")
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
        f.write(";\n")
    print(f"[ok] 已导出 {len(payload)} 位人物 -> {path}")
    return True


def load(mod_names):
    """按模块名加载人物字典，返回 [(显示名, 数据), ...]。"""
    out = []
    for mn in mod_names:
        if mn not in REGISTRY:
            print(f"[x] 未知模块 {mn}（可选：{', '.join(REGISTRY)}）")
            sys.exit(1)
        mod = importlib.import_module(f"seed_{mn}")
        for disp, attr in REGISTRY[mn]:
            data = getattr(mod, attr, None)
            if data is None:
                print(f"[x] 模块 seed_{mn} 缺少常量 {attr}")
                sys.exit(1)
            out.append((disp, data))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modules", nargs="*", default=list(REGISTRY),
                    help="seed 模块名（不含 seed_ 前缀），默认全部")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--list", action="store_true", help="列出可导入模块与人物后退出")
    ap.add_argument("--export", action="store_true",
                    help="导入后导出默认人物（is_active=1）到 ../figure_data.js")
    args = ap.parse_args()

    if args.list:
        for mn, items in REGISTRY.items():
            print(f"  seed_{mn}.py")
            for disp, attr in items:
                print(f"      {attr:8s} -> {disp}")
        return

    if not os.path.exists(args.db):
        print(f"[x] 数据库不存在：{args.db}，请先 `python database/manage.py init`")
        sys.exit(1)

    payload = load(args.modules)

    failed = False
    for name, data in payload:
        errs = validate_figure(name, data)
        if errs:
            failed = True
            print(f"[x] {name} 数据自检失败：")
            for e in errs:
                print(f"    [!] {e}")
        else:
            print(f"[ok] {name} 数据自检通过")
    if failed:
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        ensure_schema(conn)
        for name, data in payload:
            upsert(conn, name, data)
        conn.commit()
        print(f"\n[ok] 导入完成（{len(payload)} 位人物）。")
        if args.export:
            export_js(conn, os.path.join(BASE_DIR, "..", "figure_data.js"))
        print("     python database/verify_curves.py   # 校验国运 / 气运曲线")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.path.insert(0, BASE_DIR)
    main()
