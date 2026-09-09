# -*- coding: utf-8 -*-
"""
王朝K线图 · 桌面版入口（MVP）
============================
基于 pywebview 的原生窗口壳：
  - 开发运行:  python app.py
  - 冒烟模式:  KLINE_SMOKE=1 python app.py   （启动 5 秒后自动关闭，用于 CI/测试）
  - 打包发布:  build.bat （PyInstaller 单文件 exe）

数据流（MVP 保持不变）:
  database/manage.py export -> data.js -> index.html 静态读取。
  js_api 预留 get_dynasty()，后续前端可从"读文件"平滑切到"调接口"。
"""
import json
import os
import pathlib
import sqlite3
import sys
import threading

import webview  # pywebview

BASE_DIR = pathlib.Path(__file__).resolve().parent

# PyInstaller --onefile 模式下，资源解压到 sys._MEIPASS 临时目录
RESOURCE_BASE = pathlib.Path(getattr(sys, "_MEIPASS", BASE_DIR))

WINDOW_TITLE = "王朝交易所 · DYNASTY EXCHANGE"
HOME_PAGE = "dynasty-exchange.html"   # 启动首页（设计稿）；index.html 为行情盘面页
MIN_SIZE = (960, 640)
DEFAULT_SIZE = (1280, 860)


def resource_path(rel: str) -> str:
    """解析随 exe 打包的静态资源路径（兼容开发与 frozen 两种模式）。"""
    return str(RESOURCE_BASE / rel)


def ensure_data_js() -> str:
    """
    返回可用的 data.js 路径。
    开发模式下若缺失，则调用 database/manage.py export 自动导出；
    frozen 模式下 data.js 已打包进 exe，直接返回。
    """
    if getattr(sys, "frozen", False):
        return resource_path("data.js")
    data_js = BASE_DIR / "data.js"
    if not data_js.exists():
        import subprocess

        subprocess.run(
            [sys.executable, str(BASE_DIR / "database" / "manage.py"), "export"],
            check=True, cwd=str(BASE_DIR),
        )
    return str(data_js)


def _camel(key: str) -> str:
    """config 表键名 snake_case -> camelCase（与 manage.py 导出规则一致）。"""
    parts = key.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _coerce(v: str):
    """config 值：纯整数 -> int，小数 -> float，其余保留字符串。"""
    import re
    if v.lstrip("-").isdigit():
        return int(v)
    if re.match(r"^-?\d+\.\d+$", v):
        return float(v)
    return v


class Api:
    """
    暴露给前端 JS 的接口（pywebview js_api）。
    数据唯一来源是打包的 SQLite；data.js 仅作为浏览器演示模式的回退。
    输出结构与 window.DYNASTY_DATA 完全一致，前端一套渲染逻辑通吃。
    """

    def _connect(self):
        conn = sqlite3.connect(resource_path("database/dynasty.db"))
        conn.row_factory = sqlite3.Row
        return conn

    def list_dynasties(self) -> str:
        """王朝列表（类似股票自选列表），供头部下拉切换。

        hasData：锚点数 >=2 才能生成 K 线；否则前端按"筹备中"占位渲染。
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT d.code, d.name, d.range_label, d.start_year, d.end_year, "
                "       d.is_active, "
                "       (SELECT COUNT(*) FROM anchors a WHERE a.dynasty_id=d.id) AS n_anchor "
                "FROM dynasties d ORDER BY d.start_year").fetchall()
        finally:
            conn.close()
        return json.dumps([{
            "code": r["code"], "name": r["name"],
            "rangeLabel": r["range_label"],
            "startYear": r["start_year"], "endYear": r["end_year"],
            "isActive": bool(r["is_active"]),
            "hasData": r["n_anchor"] >= 2,
        } for r in rows], ensure_ascii=False)

    def get_dynasty(self, code: str) -> str:
        """按代码返回单个王朝的完整盘面数据 JSON。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM dynasties WHERE code=? LIMIT 1", (code,)).fetchone()
            if row is None:
                return json.dumps({"error": f"unknown dynasty: {code}"},
                                  ensure_ascii=False)
            dynasty = {
                "code": row["code"], "name": row["name"],
                "rangeLabel": row["range_label"],
                "startYear": row["start_year"], "endYear": row["end_year"],
                "issuePrice": row["issue_price"], "peakYear": row["peak_year"],
                "seed": row["seed"],
            }
            events = [dict(r) for r in conn.execute(
                'SELECT year, title, term, dir, mag, description AS "desc" '
                "FROM events WHERE dynasty_id=? ORDER BY sort, year",
                (row["id"],))]
            emperors = [{"name": r["name"], "full": r["full_name"],
                         "s": r["start_year"], "e": r["end_year"]}
                        for r in conn.execute(
                "SELECT name, full_name, start_year, end_year FROM emperors "
                "WHERE dynasty_id=? ORDER BY sort", (row["id"],))]
            anchors = [list(r) for r in conn.execute(
                "SELECT year, value FROM anchors WHERE dynasty_id=? "
                "ORDER BY sort, year", (row["id"],))]
            config = {_camel(r["key"]): _coerce(r["value"])
                      for r in conn.execute("SELECT key, value FROM config")}
        finally:
            conn.close()
        return json.dumps({
            "dynasty": dynasty, "events": events,
            "emperors": emperors, "anchors": anchors, "config": config,
        }, ensure_ascii=False)


def has_webview2() -> bool:
    """预检 WebView2 Runtime（Win10/11 一般自带；缺失时给出可读提示）。"""
    import winreg

    keys = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
         r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
         r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    )
    for hive, path in keys:
        try:
            with winreg.OpenKey(hive, path):
                return True
        except OSError:
            continue
    return False


def alert_missing_webview2() -> None:
    msg = ("未检测到 Microsoft WebView2 Runtime，无法启动窗口。\n\n"
           "请安装后重试：https://developer.microsoft.com/microsoft-edge/webview2/")
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, WINDOW_TITLE, 0x10)
    except Exception:
        print(msg, file=sys.stderr)


def main() -> int:
    if not has_webview2():
        alert_missing_webview2()
        return 1

    index_uri = pathlib.Path(resource_path(HOME_PAGE)).as_uri()
    window = webview.create_window(
        WINDOW_TITLE,
        index_uri,
        js_api=Api(),
        width=DEFAULT_SIZE[0], height=DEFAULT_SIZE[1],
        min_size=MIN_SIZE,
        background_color="#FFFFFF",
    )

    # 冒烟模式：窗口真实创建并渲染 5 秒后自动关闭（供测试验证）
    if os.environ.get("KLINE_SMOKE"):
        threading.Timer(5.0, lambda: window.destroy()).start()

    try:
        webview.start()
        return 0
    except Exception as e:  # noqa: BLE001 —— 兜底给出可读错误而非静默崩溃
        if getattr(sys, "frozen", False):
            alert_missing_webview2()
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
