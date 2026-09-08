# -*- coding: utf-8 -*-
"""
批量导入秦、汉种子数据到 SQLite。

用法：
    python database/import_qin_han.py            # 导入（已存在则跳过）
    python database/import_qin_han.py --force    # 删除旧记录后重导

注意：本脚本只新增秦、汉两个王朝（is_active=0），
      不会改动现有的大宋（is_active=1）及其配置。
"""
import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seed_qin_han import QIN, HAN  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dynasty.db")

DIRS = ("bull", "bear", "vol", "neutral")
MAG_RE = re.compile(r"^[+±-][大小中巨]$")


def next_year(y):
    """纪年的下一个年份（公元纪年无 0 年：-1 之后是 1）。"""
    return 1 if y == -1 else y + 1


def validate_dynasty(name, data):
    """数据自检：皇帝无缝覆盖、事件年份合法、mag 格式、锚点升序。"""
    d, emps, evs, anchors = data["dynasty"], data["emperors"], data["events"], data["anchors"]
    errors = []
    s0, e0 = d["start_year"], d["end_year"]
    if s0 > e0:
        errors.append(f"{name} 起始年 {s0} 晚于结束年 {e0}")

    # 皇帝无缝覆盖（用纪年连续规则：无 0 年）
    cur = s0
    for i, (nm, full, s, e) in enumerate(emps):
        if s > e:
            errors.append(f"{name} 皇帝 {nm} 区间非法 {s}>{e}")
        if s != cur:
            errors.append(f"{name} 皇帝区间断裂：期望 {cur}，实际 {nm}={s}")
        cur = next_year(e)
    if cur != next_year(e0):
        errors.append(f"{name} 皇帝区间未覆盖到 {e0}（止于 {e-1}）")

    # 事件
    for y, t, term, dr, mag, desc in evs:
        if not (s0 <= y <= e0):
            errors.append(f"{name} 事件「{t}」年份 {y} 超出 [{s0},{e0}]")
        if dr not in DIRS:
            errors.append(f"{name} 事件「{t}」dir 非法 {dr}")
        if not MAG_RE.match(mag or ""):
            errors.append(f"{name} 事件「{t}」mag 非法 {mag}")

    # 锚点升序
    ys = [a[0] for a in anchors]
    if ys != sorted(ys):
        errors.append(f"{name} 锚点年份未升序")
    for y, v in anchors:
        if not (s0 <= y <= e0):
            errors.append(f"{name} 锚点年份 {y} 超出 [{s0},{e0}]")
        if v <= 0:
            errors.append(f"{name} 锚点值 {v} 非法（须为正）")

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
             d["issue_price"], d["peak_year"], d["seed"], d["is_active"], d["notes"], did))
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
        [(did, y, t, term, dr, mag, desc, i) for i, (y, t, term, dr, mag, desc) in enumerate(evs)])
    conn.executemany(
        "INSERT INTO anchors(dynasty_id,year,value,sort) VALUES(?,?,?,?)",
        [(did, y, v, i) for i, (y, v) in enumerate(anchors)])
    print(f"      皇帝 {len(emps)} / 事件 {len(evs)} / 锚点 {len(anchors)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="删除已有秦汉记录后重导")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[x] 数据库不存在：{args.db}，请先 `python database/manage.py init`")
        sys.exit(1)

    for name, data in (("秦", QIN), ("汉", HAN)):
        errs = validate_dynasty(name, data)
        if errs:
            print(f"[x] {name} 数据自检失败：")
            for e in errs:
                print(f"    [!] {e}")
            sys.exit(1)
        print(f"[ok] {name} 数据自检通过")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for name, data in (("秦", QIN), ("汉", HAN)):
            upsert(conn, name, data)
        conn.commit()
        print("\n[ok] 导入完成。请运行：")
        print("     python database/manage.py show       # 查看活跃王朝（仍是大宋）")
        print("     python database/manage.py validate   # 校验活跃王朝（大宋）")
        print("     切换王朝：python database/manage.py dynasty update --name 大秦王朝 ... ")
        print("       （或直接将目标王朝 is_active 置 1 后重新 export）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
