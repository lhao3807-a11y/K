# -*- coding: utf-8 -*-
"""数据库管理工具测试：建库、导出、CRUD、校验规则。"""
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
MANAGE = os.path.join(PROJECT, "database", "manage.py")


def run(args, expect_code=0):
    """运行 manage.py 子命令，返回 (returncode, stdout+stderr)。"""
    r = subprocess.run([sys.executable, MANAGE] + args,
                       capture_output=True, encoding="utf-8", errors="replace")
    assert r.returncode == expect_code, (
        f"期望退出码 {expect_code}，实际 {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}")
    return r.stdout + r.stderr


def load_datajs(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"window\.DYNASTY_DATA\s*=\s*(\{.*\});\s*$", text, re.S)
    assert m, "data.js 中找不到 window.DYNASTY_DATA"
    return json.loads(m.group(1))


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """临时数据库 + 导出的 data.js。"""
    tmp = tmp_path_factory.mktemp("db")
    db = str(tmp / "test.db")
    out = str(tmp / "data.js")
    run(["--db", db, "init"])
    run(["--db", db, "export", "--out", out])
    return db, out


# ---------- 建库与导出 ----------


def test_init_counts(env):
    db, _ = env
    s = run(["--db", db, "show"])
    assert "emperors   18 条" in s
    assert "events     21 条" in s
    assert "anchors    27 条" in s


def test_export_structure_matches_frontend(env):
    _, out = env
    d = load_datajs(out)
    assert set(d.keys()) == {"dynasty", "emperors", "events", "anchors", "config"}
    assert d["dynasty"]["code"] == "DASONG.960"
    assert d["dynasty"]["startYear"] == 960 and d["dynasty"]["endYear"] == 1279
    assert d["dynasty"]["issuePrice"] == 100 and d["dynasty"]["peakYear"] == 1082
    assert d["dynasty"]["seed"] == 9601279
    # 事件字段与前端 EVENTS 一一对应
    assert all(set(e) == {"year", "title", "term", "dir", "mag", "desc"} for e in d["events"])
    assert all(set(x) == {"name", "full", "s", "e"} for x in d["emperors"])
    # 与原 index.html 首尾事件一致
    assert d["events"][0] == {"year": 960, "title": "陈桥兵变 · 黄袍加身", "term": "IPO 上市",
                              "dir": "bull", "mag": "+大",
                              "desc": "赵匡胤黄袍加身，代周建宋，国运指数以发行价 100 点挂牌上市。"}
    assert d["events"][-1]["year"] == 1279 and d["events"][-1]["term"] == "摘牌退市"
    assert d["anchors"][0] == [960, 100] and d["anchors"][-1] == [1279, 2]
    assert d["config"] == {"spanFull": 120, "maYear": 20, "maEmperor": 3}


def test_emperor_coverage_seamless(env):
    _, out = env
    d = load_datajs(out)
    emps = d["emperors"]
    assert emps[0]["s"] == 960 and emps[-1]["e"] == 1279
    for a, b in zip(emps, emps[1:]):
        assert b["s"] == a["e"] + 1, f"{a['name']} 与 {b['name']} 区间不连续"


# ---------- CRUD ----------


def test_event_add_update_delete(env):
    db, out = env
    # 负号开头的 mag 必须用等号写法，否则 argparse 视为未知选项
    run(["--db", db, "event", "add", "--year", "1189", "--title", "测试事件",
         "--term", "利好出尽", "--dir", "bear", "--mag=-小", "--desc", "测试用"])
    run(["--db", db, "export", "--out", out])
    d = load_datajs(out)
    assert len(d["events"]) == 22
    assert any(e["year"] == 1189 and e["title"] == "测试事件" for e in d["events"])

    # update：找到该事件 id 后改标题
    s = run(["--db", db, "event", "list", "--year", "1189"])
    eid = int(re.search(r"#(\d+)", s).group(1))
    run(["--db", db, "event", "update", str(eid), "--title", "测试事件改"])
    run(["--db", db, "export", "--out", out])
    d = load_datajs(out)
    assert any(e["title"] == "测试事件改" for e in d["events"])

    run(["--db", db, "event", "delete", str(eid)])
    run(["--db", db, "export", "--out", out])
    d = load_datajs(out)
    assert len(d["events"]) == 21 and not any(e["year"] == 1189 for e in d["events"])


def test_event_validation(env):
    db, _ = env
    # dir 非法：argparse choices 拒绝，退出码 2
    run(["--db", db, "event", "add", "--year", "1100", "--title", "x", "--term", "y",
         "--dir", "boom", "--mag=+大"], expect_code=2)
    # mag 格式非法：业务校验拒绝，退出码 1
    run(["--db", db, "event", "add", "--year", "1100", "--title", "x", "--term", "y",
         "--dir", "bull", "--mag", "很大"], expect_code=1)
    # 年份超出王朝区间：业务校验拒绝，退出码 1
    run(["--db", db, "event", "add", "--year", "900", "--title", "x", "--term", "y",
         "--dir", "bull", "--mag=+大"], expect_code=1)


def test_emperor_overlap_rejected(env):
    db, _ = env
    # 与太宗（977-997）重叠
    run(["--db", db, "emperor", "add", "--name", "僭主", "--full", "测试 僭主",
         "--start", "990", "--end", "1000"], expect_code=1)


def test_emperor_gap_blocks_export(tmp_path):
    """使用独立数据库，避免污染共享 fixture。"""
    db = str(tmp_path / "gap.db")
    out = str(tmp_path / "gap.js")
    run(["--db", db, "init"])
    s = run(["--db", db, "emperor", "list"])
    eid = int(re.search(r"#(\d+)", s).group(1))  # 第一位皇帝（太祖）
    run(["--db", db, "emperor", "delete", str(eid)])
    run(["--db", db, "export", "--out", out], expect_code=1)
    run(["--db", db, "validate"], expect_code=1)


def test_config_set_reflected_in_export(env, tmp_path):
    db, _ = env
    run(["--db", db, "config", "set", "span_full", "80"])
    out2 = str(tmp_path / "d2.js")
    run(["--db", db, "export", "--out", out2])
    assert load_datajs(out2)["config"]["spanFull"] == 80


def test_anchor_update(env, tmp_path):
    db, _ = env
    s = run(["--db", db, "anchor", "list"])
    aid = int(re.search(r"#(\d+)", s).group(1))  # 首锚点 960->100
    run(["--db", db, "anchor", "update", str(aid), "--value", "101"])
    out3 = str(tmp_path / "d3.js")
    run(["--db", db, "export", "--out", out3])
    assert load_datajs(out3)["anchors"][0] == [960, 101]


# ---------- 前端文件 ----------


def test_index_html_reads_data_layer():
    with open(os.path.join(PROJECT, "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert '<script src="./data.js"></script>' in html
    assert "window.DYNASTY_DATA" in html
    assert "D.dynasty.issuePrice" in html
    # 前端不再硬编码事件/皇帝/锚点数据集
    assert "const EVENTS = [" not in html and "const EMPERORS = [" not in html
    assert "const ANCHORS = [" not in html
