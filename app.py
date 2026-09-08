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

WINDOW_TITLE = "王朝 K 线图 · DASONG.960"
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


class Api:
    """暴露给前端 JS 的接口（pywebview js_api）。MVP 预留，前端尚未调用。"""

    def get_dynasty(self) -> str:
        """
        从打包的 SQLite 返回王朝数据 JSON（前端可直接 JSON.parse）。
        输出结构与 data.js（window.DYNASTY_DATA）完全一致，方便前端
        后续从"读文件"平滑切换到"调接口"。
        """
        db = resource_path("database/dynasty.db")
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM dynasties WHERE is_active=1 LIMIT 1").fetchone()
            dynasty = {
                "code": row["code"], "name": row["name"],
                "rangeLabel": row["range_label"],
                "startYear": row["start_year"], "endYear": row["end_year"],
                "issuePrice": row["issue_price"], "peakYear": row["peak_year"],
                "seed": row["seed"],
            }
            events = [dict(r) for r in conn.execute(
                'SELECT year, title, term, dir, mag, description AS "desc" '
                "FROM events ORDER BY sort, year")]
            emperors = [{"name": r["name"], "full": r["full_name"],
                         "s": r["start_year"], "e": r["end_year"]}
                        for r in conn.execute(
                "SELECT name, full_name, start_year, end_year FROM emperors ORDER BY sort")]
            anchors = [list(r) for r in conn.execute(
                "SELECT year, value FROM anchors ORDER BY sort, year")]
        finally:
            conn.close()
        return json.dumps({
            "dynasty": dynasty, "events": events,
            "emperors": emperors, "anchors": anchors,
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

    index_uri = pathlib.Path(resource_path("index.html")).as_uri()
    window = webview.create_window(
        WINDOW_TITLE,
        index_uri,
        js_api=Api(),
        width=DEFAULT_SIZE[0], height=DEFAULT_SIZE[1],
        min_size=MIN_SIZE,
        background_color="#0d1117",
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
