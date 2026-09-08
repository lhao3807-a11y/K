# -*- coding: utf-8 -*-
"""
通用王朝种子数据导入器
======================
把任意 seed 模块里的王朝数据写入 SQLite（已存在则 upsert）。

用法：
    python database/import_seed.py                 # 导入全部已知王朝
    python database/import_seed.py sui_tang        # 只导入 seed_sui_tang.py
    python database/import_seed.py sui_tang yuan_ming_qing

    python database/import_seed.py --list          # 列出可导入的模块与王朝

设计：
  - 每个 seed 模块暴露若干「王朝字典」常量（含 dynasty/emperors/events/anchors 四键）。
  - 校验规则与 import_qin_han.py 一致，另加「事件年份升序」约束
    （前端 markPoint 的纵向错开逻辑依赖 EVENTS 按年份有序）。
  - 只新增/更新目标王朝，绝不改动其他王朝（尤其是 is_active=1 的大宋）。
"""
import argparse
import importlib
import os
import re
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dynasty.db")

DIRS = ("bull", "bear", "vol", "neutral")
MAG_RE = re.compile(r"^[+±-][大小中巨]$")

# 模块 -> [(显示名, 常量名), ...]
REGISTRY = {
    "qin_han":          [("秦", "QIN"), ("汉", "HAN")],
    "sui_tang":         [("隋", "SUI"), ("唐", "TANG")],
    "yuan_ming_qing":   [("元", "YUAN"), ("明", "MING"), ("清", "QING")],
}


def next_year(y):
    """纪年的下一个年份（公元纪年无 0 年：-1 之后是 1）。"""
    return 1 if y == -1 else y + 1


def validate_dynasty(name, data):
    """数据自检：皇帝无缝覆盖、事件年份合法且升序、mag 格式、锚点升序。"""
    d, emps, evs, anchors = data["dynasty"], data["emperors"], data["events"], data["anchors"]
    errors = []
    s0, e0 = d["start_year"], d["end_year"]
    if s0 > e0:
        errors.append(f"{name} 起始年 {s0} 晚于结束年 {e0}")

    # 皇帝无缝覆盖（纪年连续规则：无 0 年）
    cur = s0
    last = None
    for nm, full, s, e in emps:
        if s > e:
            errors.append(f"{name} 皇帝 {nm} 区间非法 {s}>{e}")
        if s != cur:
            errors.append(f"{name} 皇帝区间断裂：期望 {cur}，实际 {nm}={s}")
        cur = next_year(e)
        last = e
    if last is not None and cur != next_year(e0):
        errors.append(f"{name} 皇帝区间未覆盖到 {e0}（止于 {last}）")

    # 事件：年份合法 + dir/mag 合法 + 年份升序
    prev_y = None
    for y, t, term, dr, mag, desc in evs:
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

    # 见顶年须落在区间内
    pk = d.get("peak_year")
    if pk is not None and not (s0 <= pk <= e0):
        errors.append(f"{name} peak_year {pk} 超出 [{s0},{e0}]")

    return errors


def upsert(conn, name, data):
    d, emps, evs, anchors = data["dynasty"], data["emperors"], data["events"], data["anchors"]
    code = d["code"]
    row = conn.execute("SELECT id FROM dynasties WHERE code=?", (code,)).fetchone()
    if row:
        did = row[0]
        conn.execute(
            "UPDATE dynasties SET name=?,range_label=?,start_year=?,end_year=?,"
            "issue_price=?,peak_year=?,seed=?,is_active=?,notes=? WHERE id=?",
            (d["name"], d["range_label"], d["start_year"], d["end_year"],
             d["issue_price"], d["peak_year"], d["seed"], d["is_active"],
             d["notes"], did))
        conn.execute("DELETE FROM emperors WHERE dynasty_id=?", (did,))
        conn.execute("DELETE FROM events WHERE dynasty_id=?", (did,))
        conn.execute("DELETE FROM anchors WHERE dynasty_id=?", (did,))
        print(f"[ok] 已更新 {name}（code={code}）")
    else:
        cur = conn.execute(
            "INSERT INTO dynasties(code,name,range_label,start_year,end_year,issue_price,"
            "peak_year,seed,is_active,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (d["code"], d["name"], d["range_label"], d["start_year"], d["end_year"],
             d["issue_price"], d["peak_year"], d["seed"], d["is_active"], d["notes"]))
        did = cur.lastrowid
        print(f"[ok] 已新增 {name}（code={code}）")

    conn.executemany(
        "INSERT INTO emperors(dynasty_id,name,full_name,start_year,end_year,sort) "
        "VALUES(?,?,?,?,?,?)",
        [(did, nm, full, s, e, i) for i, (nm, full, s, e) in enumerate(emps)])
    conn.executemany(
        "INSERT INTO events(dynasty_id,year,title,term,dir,mag,description,sort) "
        "VALUES(?,?,?,?,?,?,?,?)",
        [(did, y, t, term, dr, mag, desc, i)
         for i, (y, t, term, dr, mag, desc) in enumerate(evs)])
    conn.executemany(
        "INSERT INTO anchors(dynasty_id,year,value,sort) VALUES(?,?,?,?)",
        [(did, y, v, i) for i, (y, v) in enumerate(anchors)])
    print(f"      皇帝 {len(emps)} / 事件 {len(evs)} / 锚点 {len(anchors)}")


def load(mod_names):
    """按模块名加载王朝字典，返回 [(显示名, 数据), ...]。"""
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
    ap.add_argument("--list", action="store_true", help="列出可导入模块与王朝后退出")
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
        errs = validate_dynasty(name, data)
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
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for name, data in payload:
            upsert(conn, name, data)
        conn.commit()
        print(f"\n[ok] 导入完成（{len(payload)} 个王朝）。")
        print("     python database/manage.py show       # 查看活跃王朝（仍是大宋）")
        print("     python database/manage.py validate   # 校验活跃王朝（大宋）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
