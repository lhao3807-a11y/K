# -*- coding: utf-8 -*-
"""桌面壳（app.py）测试：资源解析、js_api 数据、WebView2 预检、冒烟启动。"""
import json
import os
import pathlib
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
                "isActive", "hasData"} <= set(d) for d in lst)


def test_api_list_dynasties_has_data_flag():
    """hasData：锚点>=2 才能生成 K 线；秦→清注册表已入库，逐支判定。"""
    lst = json.loads(app.Api().list_dynasties())
    by = {d["code"]: d for d in lst}
    assert by["DASONG.960"]["hasData"] is True
    # 八大统一王朝 + 两晋（西晋+东晋合并）已录入完整数据，hasData 应为 True
    for code in ("DAQIN.221", "DAHAN.202", "JIN.266", "SUI.581", "TANG.618",
                 "DASONG.960", "YUAN.1271", "MING.1368", "QING.1644"):
        if code in by:
            assert by[code]["hasData"] is True, f"{code} 应有完整数据"
    # 分裂期（三国/南北朝/五代）仍是纯元数据占位
    for code in ("SG.220", "NBC.420", "WUDAI.907"):
        if code in by:
            assert by[code]["hasData"] is False, f"{code} 应为占位"
    # 按 start_year 升序，覆盖秦→清
    years = [d["startYear"] for d in lst]
    assert years == sorted(years)
    assert lst[0]["startYear"] == -221 and lst[-1]["startYear"] == 1644


def test_api_get_dynasty_returns_frontend_schema():
    """js_api 输出与 data.js（window.DYNASTY_DATA）结构完全一致。"""
    api = app.Api()
    d = json.loads(api.get_dynasty("DASONG.960"))
    assert set(d.keys()) == {"dynasty", "emperors", "events", "anchors", "config"}
    assert d["dynasty"]["code"] == "DASONG.960"
    assert d["dynasty"]["startYear"] == 960 and d["dynasty"]["endYear"] == 1279
    assert d["dynasty"]["issuePrice"] == 100 and d["dynasty"]["peakYear"] == 1081
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


def test_build_packs_all_page_assets():
    """所有页面引用的本地脚本与页面间链接必须全部出现在打包清单
    （build.bat 与 spec），否则 exe 内 404、二级页面崩溃
    （V1.1.0 曾漏掉 kline.js 与 figure.html/figure_data.js）。"""
    import re
    root = pathlib.Path(app.BASE_DIR)
    pages = [p.name for p in root.glob("*.html")]
    assert {"index.html", "dynasty-exchange.html", "figure.html"} <= set(pages)
    referenced = set()
    for page in pages:
        html = (root / page).read_text(encoding="utf-8")
        referenced |= set(re.findall(r'<script src="\./([^"]+)"></script>', html))
        # 页面间本地链接（导航/卡片跳转），如 ./figure.html
        referenced |= {m.lstrip("./") for m in re.findall(
            r'(?:href|location\.href\s*=\s*)[\'"]\./?([\w-]+\.html)', html)}
    for must in ("kline.js", "figure.html", "figure_data.js"):
        assert must in referenced, f"扫描器未捕获 {must}，正则需更新"
    build_bat = (root / "build.bat").read_text(encoding="utf-8")
    spec = (root / "DynastyKline.spec").read_text(encoding="utf-8")
    for asset in referenced:
        assert f'"{asset};."' in build_bat, f"build.bat 缺 {asset}"
        assert f"('{asset}', '.')" in spec, f"DynastyKline.spec 缺 {asset}"


def test_exchange_home_wired_to_js_api_and_navigation():
    """首页动态化：js_api 驱动 + 卡片跳转 K 线页深链 + 筛选/搜索。"""
    with open(app.resource_path("dynasty-exchange.html"), encoding="utf-8") as f:
        js = f.read()
    assert "list_dynasties" in js and "get_dynasty(" in js
    assert "index.html#" in js          # 卡片 → 盘面页深链
    assert "buildCandles" in js         # 行情数字由真实数据计算（与盘面页同算法）
    assert "miniKlineSVG" in js         # 卡片迷你走势动态生成
    assert "kline.js" in js             # K 线算法统一走公共引擎，页面内不得另抄一份
    # 跨 0 年王朝（大汉 前202~220）：K 线循环必须跳过 0 年，否则比 exe 多 1 根
    # 且随机序列错位，两页数字不一致。该逻辑现由 kline.js 的 nextYear 统一承担
    with open(app.resource_path("kline.js"), encoding="utf-8") as f:
        kjs = f.read()
    assert "y === -1 ? 1 : y + 1" in kjs
    # 历史最高年份须经 yearsOf 序列（跳 0）计算
    assert "function yearsOf" in js
    assert "hiY=ys[i]" in js
    # 新 UI：筛选 chips（全部/上涨/下跌/大一统/分裂期）+ 搜索框过滤卡片
    assert 'data-filter="up"' in js and 'data-filter="split"' in js
    assert "applyFilter" in js and "searchInput" in js


def test_exchange_home_featured_random_and_extreme_marks():
    """首页焦点区：每次进入随机标的 + 极值锚点标注（与盘面页同算法）+ 动效与交互。"""
    with open(app.resource_path("dynasty-exchange.html"), encoding="utf-8") as f:
        js = f.read()
    assert "extMap" in js and "RANK=" in js   # 极值→事件绑定（巨>大>中>小）
    assert "pt-mark" in js                    # 极值标注样式钩子
    assert "Math.random()*pool.length" in js  # 焦点标的每次进入随机挑选
    assert "withData" in js                   # 随机池限定有数据王朝
    assert "countUp" in js                    # 关键数字滚动动画
    assert "animation-delay" in js            # 卡片错峰入场
    assert "prefers-reduced-motion" in js     # 尊重系统减弱动效设置


def test_chart_page_supports_deep_link_and_back():
    """盘面页：hash 深链选王朝 + 返回交易所入口 + 同页 hash 变化响应。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        js = f.read()
    assert "location.hash" in js
    assert "dynasty-exchange.html" in js and 'backHome' in js
    # 同页 hashchange（#A → #B 不触发 reload）也要切换王朝
    assert "hashchange" in js


def test_watchlist_persisted_and_keyboard_nav():
    """自选持久化（localStorage 共用 key）+ 盘面页 ←/→ 键盘切换标的。"""
    idx = app.resource_path("index.html")
    home = app.resource_path("dynasty-exchange.html")
    with open(idx, encoding="utf-8") as f:
        chart = f.read()
    with open(home, encoding="utf-8") as f:
        home_js = f.read()
    with open(app.__file__, encoding="utf-8") as f:
        app_js = f.read()
    # 两页共用同一存储 key；写入需 try/catch 兜底
    assert chart.count("'dynasty.watchlist'") == 1 and "'dynasty.watchlist'" in home_js
    assert "function saveFavs" in chart and "localStorage.setItem" in chart
    assert "function loadFavs" in chart and "function loadFavs" not in home_js  # 首页只读
    assert "favCodes.has(c.getAttribute('data-code'))" in home_js               # 首页 chip 过滤
    # pywebview 默认隐私模式禁用存储，必须显式关闭
    assert "private_mode=False" in app_js
    # 键盘 ←/→ 切换：跳过输入控件焦点，越界不动
    assert "'ArrowLeft'" in chart and "'ArrowRight'" in chart
    assert "tag==='INPUT'||tag==='SELECT'||tag==='TEXTAREA'" in chart
    # 「←/→ 切换」提示文字已移除，但键盘切换与两侧箭头功能保留
    assert "kbdHint" not in chart and "kbd-hint" not in chart


def test_nav_watchlist_side_arrows_and_follow_card():
    """顶层导航「⭐ 自选」+ 盘面页两侧箭头（与键盘同功能）+ 详情浮卡跟随鼠标。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        chart = f.read()
    with open(app.resource_path("dynasty-exchange.html"), encoding="utf-8") as f:
        home = f.read()
    # 两页顶层导航均有自选入口；详情页经 #fav 深链回首页并激活自选筛选
    assert 'id="navFav"' in chart and 'id="navFav"' in home
    assert 'href="dynasty-exchange.html#fav"' in chart
    assert "location.hash==='#fav'" in home and "function activateFavFilter" in home
    assert 'id="gridEmpty"' in home                      # 自选为空/搜索无结果时的空态提示
    # 两侧箭头与键盘共用 stepTo，下拉/键盘/箭头统一走 switchTo
    assert 'id="navPrev"' in chart and 'id="navNext"' in chart
    assert "function stepTo" in chart and "function switchTo" in chart
    assert "np.addEventListener('click',()=>stepTo(-1))" in chart
    assert "nn.addEventListener('click',()=>stepTo(1))" in chart
    # 浮卡随鼠标：显示时定位到光标处，光标悬入卡面即停止跟随
    assert "function moveCard" in chart and "function showCardAtCursor" in chart
    assert "cardFollow=false" in chart and "closest('#card')" in chart
    # 事件与皇帝两条展示路径都要唤起跟随
    assert chart.count("showCardAtCursor();") == 2
    # 词条悬停出浮卡、光标离开词条立即消失（大事记 + 皇帝条）
    assert "function hideCard" in chart
    assert chart.count("mouseleave',hideCard") == 2
    assert "mouseenter',()=>selectEvent(i,false)" in chart
    assert "mouseenter',()=>showEmperor(i)" in chart
    # 图表侧统一悬停式：K线/事件点 mouseover 唤卡、mouseout 收卡；无 × 关闭钮
    assert "chart.on('mouseover', onChartHover)" in chart
    assert "chart.on('mouseout', hideCard)" in chart
    assert "cardClose" not in chart


def test_app_version_matches_release_naming():
    """版本号与程序名/构建产物/页脚保持同步（版本规范见 AGENTS.md 第 3 条）。"""
    assert app.APP_VERSION == "1.3.0"
    assert app.WINDOW_TITLE == "DynastyKline—V1.3.0"
    root = pathlib.Path(app.BASE_DIR)
    assert "DynastyKline-V1.3.0" in (root / "build.bat").read_text(encoding="utf-8")
    assert "DynastyKline-V1.3.0" in (root / "DynastyKline.spec").read_text(encoding="utf-8")
    for page in ("index.html", "dynasty-exchange.html", "figure.html",
                 "figure-exchange.html"):
        with open(app.resource_path(page), encoding="utf-8") as f:
            assert "V1.3.0" in f.read(), f"{page} 页脚缺版本号"


def test_chart_page_peak_trough_event_marks():
    """峰谷锚点：局部极值绑定邻近最大冲击事件，放大锚点标识、不写文字标注。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        js = f.read()
    assert "function extremeEvents" in js       # 极值检测来自锚点序列
    assert "MAG_RANK" in js                     # 冲击幅度分级 巨>大>中>小
    assert "波峰" not in js and "波谷" not in js  # 只留锚点，不写「波峰/波谷」字样
    assert "symbolSize:ext?11:9" in js          # 极值锚点比普通事件点更大
    assert "labelFull || ext" in js             # 极值标注始终展开完整两行


def test_chart_page_data_panels_below_chart():
    """盘面页布局：关键数据 / 大事记面板位于 K 线图下方（below-row 双卡），不再侧挂。"""
    with open(app.resource_path("index.html"), encoding="utf-8") as f:
        html = f.read()
    assert 'class="below-row"' in html
    assert 0 < html.find('id="chart"') < html.find('class="below-row"')  # 数据区在图表区之后
    assert 'id="statsAnchor"' in html and 'id="eventsAnchor"' in html


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
