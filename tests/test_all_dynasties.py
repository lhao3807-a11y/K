# -*- coding: utf-8 -*-
"""全朝代数据测试：统一王朝的事件/皇帝/锚点入库完整性与国运曲线正确性。

覆盖：秦、汉、晋、隋、唐、宋、元、明、清（分裂期 SG/NBC/WUDAI 为占位，不校验）。
"""
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DB = os.path.join(PROJECT, "database", "dynasty.db")
IMPORT = os.path.join(PROJECT, "database", "import_seed.py")
VERIFY = os.path.join(PROJECT, "database", "verify_curves.py")

# code -> (显示名, 起始年, 结束年, 事件数下限, 事件数上限)
EIGHT = {
    "DAQIN.221":  ("秦", -221, -207, 10, 25),
    "DAHAN.202":  ("汉", -202, 220, 15, 25),
    "JIN.266":    ("晋", 266, 420, 15, 25),
    "SUI.581":    ("隋", 581, 618, 15, 25),
    "TANG.618":   ("唐", 618, 907, 15, 25),
    "DASONG.960": ("宋", 960, 1279, 15, 25),
    "YUAN.1271":  ("元", 1271, 1368, 15, 25),
    "MING.1368":  ("明", 1368, 1644, 15, 25),
    "QING.1644":  ("清", 1644, 1912, 15, 25),
}


def next_year(y):
    return 1 if y == -1 else y + 1


@pytest.fixture(scope="session")
def conn(tmp_path_factory):
    """在临时副本上导入并校验，避免测试污染主库（主库只在显式导入时才变）。"""
    if not os.path.exists(DB):
        pytest.skip("数据库未初始化")
    tmp_db = str(tmp_path_factory.mktemp("all") / "dynasty.db")
    shutil.copy(DB, tmp_db)

    r = subprocess.run([sys.executable, IMPORT, "--db", tmp_db],
                       capture_output=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"导入失败：\n{r.stdout}\n{r.stderr}"

    c = sqlite3.connect(tmp_db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _dyn(conn, code):
    return conn.execute("SELECT * FROM dynasties WHERE code=?", (code,)).fetchone()


def test_eight_dynasties_have_data(conn):
    """八大统一王朝都必须有皇帝、事件、锚点三套数据。"""
    for code, (name, s, e, lo, hi) in EIGHT.items():
        d = _dyn(conn, code)
        assert d is not None, f"{name}({code}) 王朝记录缺失"
        assert d["start_year"] == s, f"{name} 起始年 {d['start_year']} != {s}"
        assert d["end_year"] == e, f"{name} 结束年 {d['end_year']} != {e}"
        for tbl, mn in (("emperors", 1), ("events", lo), ("anchors", 2)):
            n = conn.execute(
                f"SELECT COUNT(*) c FROM {tbl} WHERE dynasty_id=?", (d["id"],)).fetchone()["c"]
            assert n >= mn, f"{name} {tbl} 仅 {n} 条（要求 >= {mn}）"


def test_event_count_in_range(conn):
    """每个王朝事件数在约定区间内（秦为 10–25，其余 15–25）。"""
    for code, (name, s, e, lo, hi) in EIGHT.items():
        d = _dyn(conn, code)
        n = conn.execute(
            "SELECT COUNT(*) c FROM events WHERE dynasty_id=?", (d["id"],)).fetchone()["c"]
        assert lo <= n <= hi, f"{name} 事件数 {n} 不在 [{lo},{hi}]"


def test_event_years_sorted_and_in_range(conn):
    """事件年份必须升序且在王朝区间内（前端 markPoint 错开逻辑依赖升序）。"""
    for code, (name, s, e, lo, hi) in EIGHT.items():
        d = _dyn(conn, code)
        ys = [r["year"] for r in conn.execute(
            "SELECT year FROM events WHERE dynasty_id=? ORDER BY sort", (d["id"],))]
        assert ys == sorted(ys), f"{name} 事件年份未升序"
        for y in ys:
            assert s <= y <= e, f"{name} 事件年份 {y} 超出 [{s},{e}]"


def test_emperor_coverage(conn):
    """皇帝在位区间须无缝覆盖王朝起止年（跨公元前时无 0 年）。"""
    for code, (name, s, e, lo, hi) in EIGHT.items():
        d = _dyn(conn, code)
        rows = conn.execute(
            "SELECT name,start_year,end_year FROM emperors WHERE dynasty_id=? ORDER BY sort",
            (d["id"],)).fetchall()
        cur = s
        for r in rows:
            assert r["start_year"] == cur, (
                f"{name} 皇帝区间断裂：期望 {cur}，实际 {r['name']}={r['start_year']}")
            cur = next_year(r["end_year"])
        assert cur == next_year(e), f"{name} 皇帝区间未覆盖到 {e}（止于 {cur}）"


def test_peak_year_in_range(conn):
    """见顶年必须落在王朝区间内。"""
    for code, (name, s, e, lo, hi) in EIGHT.items():
        d = _dyn(conn, code)
        pk = d["peak_year"]
        assert pk is not None, f"{name} peak_year 为空"
        assert s <= pk <= e, f"{name} peak_year {pk} 超出 [{s},{e}]"


def test_anchors_sorted_positive(conn):
    """锚点年份升序、值均为正。"""
    for code, (name, s, e, lo, hi) in EIGHT.items():
        d = _dyn(conn, code)
        rows = [r for r in conn.execute(
            "SELECT year,value FROM anchors WHERE dynasty_id=? ORDER BY sort", (d["id"],))]
        ys = [r["year"] for r in rows]
        assert ys == sorted(ys), f"{name} 锚点年份未升序"
        for r in rows:
            assert s <= r["year"] <= e, f"{name} 锚点年份 {r['year']} 超出区间"
            assert r["value"] > 0, f"{name} 锚点值 {r['value']} 须为正"


def test_verify_curves_script_passes(conn):
    """运行 verify_curves.py：曲线不得含 NaN/负值，且历史最高须落在 peak_year。"""
    r = subprocess.run([sys.executable, VERIFY], capture_output=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"曲线校验失败：\n{r.stdout}\n{r.stderr}"
    assert "[ok] 全部标的曲线校验通过" in r.stdout


def test_only_song_active(conn):
    """导入器不得改变活跃王朝（仍应且仅应为大宋）。"""
    active = conn.execute(
        "SELECT code FROM dynasties WHERE is_active=1").fetchall()
    assert [r["code"] for r in active] == ["DASONG.960"]
