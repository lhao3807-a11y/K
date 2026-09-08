# -*- coding: utf-8 -*-
"""桌面壳（app.py）测试：资源解析、js_api 数据、WebView2 预检、冒烟启动。"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
APP = os.path.join(PROJECT, "app.py")


# ---------- 资源与数据 ----------


def test_resource_path_resolves_bundled_assets():
    for rel in ("index.html", "data.js", "echarts.min.js",
                "database/dynasty.db"):
        p = app.resource_path(rel)
        assert os.path.exists(p), f"打包资源缺失: {rel} -> {p}"


def test_api_get_dynasty_returns_frontend_schema():
    """js_api 输出与 data.js（window.DYNASTY_DATA）结构完全一致。"""
    d = json.loads(app.Api().get_dynasty())
    assert set(d.keys()) == {"dynasty", "emperors", "events", "anchors"}
    assert d["dynasty"]["code"] == "DASONG.960"
    assert d["dynasty"]["startYear"] == 960 and d["dynasty"]["endYear"] == 1279
    assert d["dynasty"]["issuePrice"] == 100 and d["dynasty"]["peakYear"] == 1082
    assert all(set(e) == {"year", "title", "term", "dir", "mag", "desc"}
               for e in d["events"])
    assert all(set(x) == {"name", "full", "s", "e"} for x in d["emperors"])
    assert d["anchors"][0] == [960, 100]


def test_index_html_is_offline_only():
    """CDN 回退已移除，exe 场景不产生网络请求。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "cdn.jsdelivr.net" not in html


# ---------- WebView2 预检 ----------


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows")
def test_webview2_present_on_this_machine():
    assert app.has_webview2() is True


# ---------- 冒烟启动（真实创建窗口，5 秒自动关闭） ----------


@pytest.mark.skipif(sys.platform != "win32", reason="GUI 冒烟仅 Windows")
def test_app_smoke_launch():
    env = dict(os.environ, KLINE_SMOKE="1")
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, APP], env=env, capture_output=True,
                       encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, f"冒烟启动失败\nstdout: {r.stdout}\nstderr: {r.stderr}"
