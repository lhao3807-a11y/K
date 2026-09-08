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
    for rel in ("dynasty-exchange.html", "index.html", "data.js",
                "echarts.min.js", "database/dynasty.db"):
        p = app.resource_path(rel)
        assert os.path.exists(p), f"打包资源缺失: {rel} -> {p}"


def test_home_page_is_exchange_design():
    """启动首页为王朝交易所设计稿。"""
    assert app.HOME_PAGE == "dynasty-exchange.html"


def test_api_list_dynasties():
    """王朝列表接口：桌面端头部下拉的数据源。"""
    lst = json.loads(app.Api().list_dynasties())
    assert isinstance(lst, list) and len(lst) >= 1
    codes = {d["code"] for d in lst}
    assert "DASONG.960" in codes
    assert any(d["isActive"] for d in lst)
    assert all({"code", "name", "rangeLabel", "startYear", "endYear",
                "isActive"} <= set(d) for d in lst)


def test_api_get_dynasty_returns_frontend_schema():
    """js_api 输出与 data.js（window.DYNASTY_DATA）结构完全一致。"""
    api = app.Api()
    d = json.loads(api.get_dynasty("DASONG.960"))
    assert set(d.keys()) == {"dynasty", "emperors", "events", "anchors", "config"}
    assert d["dynasty"]["code"] == "DASONG.960"
    assert d["dynasty"]["startYear"] == 960 and d["dynasty"]["endYear"] == 1279
    assert d["dynasty"]["issuePrice"] == 100 and d["dynasty"]["peakYear"] == 1082
    assert all(set(e) == {"year", "title", "term", "dir", "mag", "desc"}
               for e in d["events"])
    assert all(set(x) == {"name", "full", "s", "e"} for x in d["emperors"])
    assert d["anchors"][0] == [960, 100]
    # config 与 data.js 导出一致（camelCase）
    assert d["config"] == {"spanFull": 120, "maYear": 20, "maEmperor": 3}


def test_api_get_dynasty_unknown_code():
    d = json.loads(app.Api().get_dynasty("NOPE.0000"))
    assert "error" in d


def test_index_html_is_offline_only():
    """CDN 回退已移除，exe 场景不产生网络请求。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "cdn.jsdelivr.net" not in html


def test_exchange_home_wired_to_js_api_and_navigation():
    """首页动态化：js_api 驱动 + 卡片/芯片跳转 K 线页深链。"""
    with open(app.resource_path("dynasty-exchange.html"), encoding="utf-8") as f:
        js = f.read()
    assert "list_dynasties" in js and "get_dynasty(" in js
    assert "index.html#" in js          # 卡片/芯片 → 盘面页深链
    assert "buildCandles" in js         # 行情数字由真实数据计算（与盘面页同算法）
    assert "miniKlineSVG" in js         # 迷你 K 线动态生成


def test_chart_page_supports_deep_link_and_back():
    """盘面页：hash 深链选王朝 + 返回交易所入口。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        js = f.read()
    assert "location.hash" in js
    assert "dynasty-exchange.html" in js and 'backHome' in js


def test_index_html_boot_uses_js_api_with_demo_fallback():
    """前端架构：桌面端 js_api 优先，data.js 仅作浏览器演示回退。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        js = f.read()
    assert "list_dynasties" in js and "get_dynasty(" in js
    assert "pywebview" in js
    assert "window.DYNASTY_DATA" in js          # 演示模式仍在
    # 关键参数不再硬编码为大宋专属值
    assert "const START=960" not in js and "mulberry32(9601279)" not in js


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
