# -*- coding: utf-8 -*-
"""
人物板块测试（李白 LIBAI.701 demo）
==================================
覆盖：表结构 / 种子数据 / 曲线数值 / JS 与 Python 算法逐位一致 /
      后端接口 / 页面结构与唯一算法源约束。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT, "database", "dynasty.db")
KLINE = os.path.join(PROJECT, "database", "kline.py")
VERIFY = os.path.join(PROJECT, "database", "verify_curves.py")
NODE = (shutil.which("node")
        or r"C:\Users\20578\.workbuddy\binaries\node\versions\22.22.2-2\node.exe")

sys.path.insert(0, os.path.join(PROJECT, "database"))
import kline  # noqa: E402


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _fig(conn, code="LIBAI.701"):
    return conn.execute("SELECT * FROM figures WHERE code=?", (code,)).fetchone()


# ---------------- 表结构 ----------------

@pytest.mark.parametrize("table", [
    "figures", "figure_periods", "figure_events", "figure_anchors"])
def test_figure_tables_exist(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    assert row is not None, f"缺少人物表 {table}"


def test_figure_events_has_quote_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(figure_events)")]
    assert "quote" in cols, "人物事件须有 quote 诗句列"
    for c in ("year", "title", "term", "dir", "mag", "description", "sort"):
        assert c in cols


# ---------------- 种子数据 ----------------

def test_libai_basic(conn):
    f = _fig(conn)
    assert f is not None, "未导入李白"
    assert f["name"] == "李白"
    assert (f["start_year"], f["end_year"]) == (701, 762)
    assert f["issue_price"] == 100
    assert f["peak_year"] == 742
    assert f["dynasty_code"] == "TANG.618"


def test_libai_periods_seamless(conn):
    f = _fig(conn)
    periods = conn.execute(
        "SELECT name,start_year,end_year FROM figure_periods "
        "WHERE figure_id=? ORDER BY sort", (f["id"],)).fetchall()
    assert len(periods) == 8
    cur = f["start_year"]
    for p in periods:
        assert p["start_year"] == cur, f"阶段断裂：{p['name']}"
        cur = p["end_year"] + 1
    assert cur - 1 == f["end_year"], "阶段未覆盖到 762"


def test_libai_events_sorted_with_quote(conn):
    f = _fig(conn)
    evs = conn.execute(
        "SELECT year,title,quote FROM figure_events WHERE figure_id=? ORDER BY sort",
        (f["id"],)).fetchall()
    assert len(evs) >= 19
    years = [e["year"] for e in evs]
    assert years == sorted(years), "事件年份须升序（前端标注错位依赖有序）"
    assert all(e["quote"] for e in evs), "每件事都应带诗句/史料佐证"
    assert 742 in years and 759 in years and 762 in years


def test_libai_anchors(conn):
    f = _fig(conn)
    anchors = conn.execute(
        "SELECT year,value FROM figure_anchors WHERE figure_id=? ORDER BY sort",
        (f["id"],)).fetchall()
    assert len(anchors) >= 13
    ys = [a["year"] for a in anchors]
    assert ys == sorted(ys)
    assert all(a["value"] > 0 for a in anchors)
    vals = dict((a["year"], a["value"]) for a in anchors)
    assert vals[742] == 210, "742 见顶锚点（奉诏入京）"
    assert vals[758] < vals[755] < vals[742], "夜郎 < 安史乱 < 翰林"


# ---------------- 曲线 ----------------

def _load_figure(conn, code="LIBAI.701"):
    """读取人物的完整曲线输入（锚点 + 事件，事件冲击参与定价）。"""
    f = _fig(conn, code)
    anchors = [(r["year"], r["value"]) for r in conn.execute(
        "SELECT year,value FROM figure_anchors WHERE figure_id=? ORDER BY sort",
        (f["id"],))]
    events = [dict(r) for r in conn.execute(
        "SELECT year,dir,mag FROM figure_events WHERE figure_id=? ORDER BY sort",
        (f["id"],))]
    periods = [(r["start_year"], r["end_year"]) for r in conn.execute(
        "SELECT start_year,end_year FROM figure_periods WHERE figure_id=? ORDER BY sort",
        (f["id"],))]
    return f, anchors, events, periods


def test_libai_curve_values(conn):
    """关键不变量：见顶年 / 破发 / 深度回撤 —— 不写死具体数字，便于后续调锚点。"""
    f, anchors, events, _ = _load_figure(conn)
    years, candles = kline.build_candles(
        f["start_year"], f["end_year"], f["peak_year"], f["seed"], anchors, events)
    assert len(candles) == 62, "701—762 共 62 根年 K"
    hi_i = max(range(len(candles)), key=lambda i: candles[i][3])
    assert int(years[hi_i]) == 742, "历史最高须落在 peak_year=742（奉诏入京）"
    assert candles[hi_i][3] > 200
    st = kline.stats(candles, f["issue_price"])
    assert st["chg"] < 0, "李白一生破发（世俗账面上的失败者）"
    assert st["max_drawdown"] < -70, "自翰林顶点到夜郎谷底应深逾七成"


def test_libai_period_candles(conn):
    f, anchors, events, periods = _load_figure(conn)
    years, candles = kline.build_candles(
        f["start_year"], f["end_year"], f["peak_year"], f["seed"], anchors, events)
    agg = kline.aggregate(candles, years, periods)
    assert len(agg) == 8
    top = max(k[3] for k in candles)
    # 供奉翰林段（742-743）：创下全曲线最高点，但收在回落位 —— 见顶即回落
    assert agg[3][3] == top
    gain = [(a[1] - a[0]) / a[0] * 100 for a in agg]
    assert gain[6] < 0, "757-758 下狱流放段应下跌"
    assert gain[7] > 0, "759-762 遇赦归途段应反抽"


def test_verify_curves_covers_figures():
    r = subprocess.run([sys.executable, VERIFY], capture_output=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"曲线校验失败：\n{r.stdout}\n{r.stderr}"
    assert "人物 · 气运指数" in r.stdout
    assert "LIBAI.701" in r.stdout


# ---------------- JS / Python 算法一致性 ----------------

def test_js_kline_matches_python():
    """用 node 跑同一份 kline.js，与 database/kline.py 逐位比对（防两套算法分叉）。"""
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        f, anchors, events, _ = _load_figure(c)
    finally:
        c.close()

    script = (
        "require(%s);" % json.dumps(os.path.join(PROJECT, "kline.js").replace("\\", "/"))
        + "const K=globalThis.KLINE;"
        + "console.log(JSON.stringify(K.buildCandles({start:%d,end:%d,peak:%d,seed:%d,anchors:%s,events:%s})));"
        % (f["start_year"], f["end_year"], f["peak_year"], f["seed"],
           json.dumps([list(a) for a in anchors]),
           json.dumps([{"year": e["year"], "dir": e["dir"], "mag": e["mag"]}
                       for e in events]))
    )
    r = subprocess.run([NODE, "-e", script], capture_output=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"node 执行失败：{r.stderr}"
    js_candles = json.loads(r.stdout.strip().splitlines()[-1])

    py_years, py_candles = kline.build_candles(
        f["start_year"], f["end_year"], f["peak_year"], f["seed"], anchors, events)
    assert len(js_candles) == len(py_candles) == 62
    assert [list(map(float, k)) for k in js_candles] == py_candles, \
        "JS 与 Python 的 K 线算法已分叉"


# ---------------- 后端接口 ----------------

def test_api_figure_endpoints():
    sys.path.insert(0, PROJECT)
    import app
    api = app.Api()
    lst = json.loads(api.list_figures())
    assert any(x["code"] == "LIBAI.701" and x["hasData"] for x in lst)

    d = json.loads(api.get_figure("LIBAI.701"))
    assert d["figure"]["peakYear"] == 742
    assert len(d["periods"]) == 8
    assert len(d["events"]) >= 19
    assert len(d["anchors"]) == 14
    assert all("quote" in e for e in d["events"])
    assert "error" in json.loads(api.get_figure("NOBODY.000"))


# ---------------- 页面结构 ----------------

def _read(name):
    with open(os.path.join(PROJECT, name), encoding="utf-8") as fh:
        return fh.read()


def test_figure_html_structure():
    html = _read("figure.html")
    assert 'src="./kline.js"' in html      # 共用唯一算法源
    assert "KLINE.buildCandles" in html
    assert "0x6D2B79F5" not in html        # 页面内不得再抄一份 mulberry32
    for i in ("fName", "fCode", "fPrice", "fChg", "chart",
              "periodBox", "eventList", "btnPeriod", "afterlifeDesc"):
        assert f'id="{i}"' in html, f"缺少元素 {i}"
    assert "get_figure" in html and "list_figures" in html
    assert "场外行情" in html               # 身后声名（第二曲线）叙事块


def test_all_pages_share_single_kline_source():
    """三个页面都须引用 kline.js，且不得各自内联算法常量。"""
    for page in ("index.html", "dynasty-exchange.html", "figure.html"):
        html = _read(page)
        assert 'src="./kline.js"' in html, f"{page} 未引用公共 K 线引擎"
        assert "0x6D2B79F5" not in html, f"{page} 仍内联了 mulberry32"


def test_exchange_home_links_to_figure():
    html = _read("dynasty-exchange.html")
    assert 'href="./figure.html"' in html
    assert "list_figures" in html          # 首页人物预览卡
    assert "teaserCard" in html
