# -*- coding: utf-8 -*-
"""秦、汉种子数据导入测试：数据自检 + 入库完整性。"""
import os
import sqlite3
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
IMPORT = os.path.join(PROJECT, "database", "import_qin_han.py")
MANAGE = os.path.join(PROJECT, "database", "manage.py")


def run(args, expect_code=0):
    r = subprocess.run([sys.executable] + args, capture_output=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == expect_code, (
        f"期望退出码 {expect_code}，实际 {r.returncode}\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}")
    return r.stdout + r.stderr


def _next_year(y):
    return 1 if y == -1 else y + 1


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """临时库：init 建大宋 + import 导入秦汉。"""
    tmp = tmp_path_factory.mktemp("qh")
    db = str(tmp / "qh.db")
    run([MANAGE, "--db", db, "init"])
    run([IMPORT, "--db", db])
    return db


def test_qin_han_present(env):
    db = env
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    codes = {r["code"]: r for r in conn.execute(
        "SELECT * FROM dynasties WHERE code IN ('DAQIN.221','DAHAN.202')")}
    conn.close()
    assert set(codes) == {"DAQIN.221", "DAHAN.202"}
    assert codes["DAQIN.221"]["start_year"] == -221
    assert codes["DAQIN.221"]["end_year"] == -207
    assert codes["DAHAN.202"]["start_year"] == -202
    assert codes["DAHAN.202"]["end_year"] == 220


def test_qin_han_event_count(env):
    db = env
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for code, lo, hi in (("DAQIN.221", 10, 25), ("DAHAN.202", 15, 25)):
        n = conn.execute(
            "SELECT COUNT(*) c FROM events e JOIN dynasties d ON e.dynasty_id=d.id "
            "WHERE d.code=?", (code,)).fetchone()["c"]
        assert lo <= n <= hi, f"{code} 事件数 {n} 不在 [{lo},{hi}]"
    conn.close()


def test_qin_han_emperor_coverage(env):
    db = env
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for code in ("DAQIN.221", "DAHAN.202"):
        d = conn.execute("SELECT * FROM dynasties WHERE code=?", (code,)).fetchone()
        rows = conn.execute(
            "SELECT start_year,end_year FROM emperors WHERE dynasty_id=? ORDER BY sort",
            (d["id"],)).fetchall()
        cur = d["start_year"]
        for r in rows:
            assert r["start_year"] == cur, f"{code} 皇帝区间断裂 {cur} vs {r['start_year']}"
            cur = _next_year(r["end_year"])
        assert cur == _next_year(d["end_year"]), f"{code} 皇帝区间未覆盖末尾"
    conn.close()


def test_qin_han_anchors_sorted(env):
    db = env
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for code in ("DAQIN.221", "DAHAN.202"):
        d = conn.execute("SELECT * FROM dynasties WHERE code=?", (code,)).fetchone()
        ys = [r["year"] for r in conn.execute(
            "SELECT year FROM anchors WHERE dynasty_id=? ORDER BY sort", (d["id"],))]
        assert ys == sorted(ys), f"{code} 锚点未升序"
    conn.close()


def test_qin_han_not_affect_active_song(env):
    db = env
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    active = conn.execute(
        "SELECT code FROM dynasties WHERE is_active=1").fetchall()
    conn.close()
    assert [r["code"] for r in active] == ["DASONG.960"]
