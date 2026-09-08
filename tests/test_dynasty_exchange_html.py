# -*- coding: utf-8 -*-
"""dynasty-exchange.html 结构校验测试（纯标准库，无需安装依赖）。

用法：
    python tests/test_dynasty_exchange_html.py
"""
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "dynasty-exchange.html"

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# svg 内部的 rect/line/path/text 等在 HTMLParser 里视作普通标签，
# 我们逐一闭合（<line .../>），自闭合由 startendtag 处理。


class StructureChecker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.counts = {
            "svg": 0,
            "chip": 0,
            "dynasty-card": 0,
            "tab": 0,
        }

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "svg":
            self.counts["svg"] += 1
        if "chip" in classes and "subnav" not in classes:
            self.counts["chip"] += 1
        if "dynasty-card" in classes:
            self.counts["dynasty-card"] += 1
        if "tab" in classes:
            self.counts["tab"] += 1
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == "svg":
            self.counts["svg"] += 1

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append(f"多余的闭合标签 </{tag}>")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(
                f"标签嵌套错误：期望 </{self.stack[-1]}>，实际 </{tag}>（位置 {self.getpos()}）"
            )


def run_tests():
    failures = []

    if not TARGET.exists():
        print(f"[FAIL] 目标文件不存在: {TARGET}")
        return 1

    html = TARGET.read_text(encoding="utf-8")

    # 1. 文档结构
    if not html.lstrip().lower().startswith("<!doctype html"):
        failures.append("缺少 <!DOCTYPE html> 声明")
    for marker, desc in [
        ("</html>", "html 闭合"),
        ("</head>", "head 闭合"),
        ("</body>", "body 闭合"),
        ("<style>", "内联样式"),
        ("<script>", "内联脚本"),
    ]:
        if marker not in html:
            failures.append(f"缺少 {desc}（{marker}）")

    # 2. 关键内容标记
    for marker, desc in [
        ("王朝交易所", "Logo"),
        ("王朝行情", "第一层 Tab"),
        ("即将上线", "人物板块徽标"),
        ("王朝标的", "第二层导航前缀"),
        ("SONG.960", "大宋代码"),
        ("全部行情", "二级导航-全部"),
        ("QIN.221", "秦"),
        ("HAN.202", "汉"),
        ("TANG.618", "唐"),
        ("YUAN.1271", "元"),
        ("MING.1368", "明"),
        ("QING.1644", "清"),
        ("陈桥兵变", "事件标注-上市"),
        ("靖康之难", "事件标注-崩盘"),
        ("崖山海战", "事件标注-退市"),
        ("发行价 100", "发行价基准线"),
        ("大秦王朝", "列表卡-秦"),
        ("大汉王朝", "列表卡-汉"),
        ("大唐王朝", "列表卡-唐"),
        ("大元王朝", "列表卡-元"),
        ("大明王朝", "列表卡-明"),
        ("大清王朝", "列表卡-清"),
        ("人物板块 · 筹备中", "人物预告"),
        ("DYNASTY EXCHANGE", "页脚品牌"),
    ]:
        if marker not in html:
            failures.append(f"缺少内容元素：{desc}（{marker}）")

    # 3. 标签配对
    checker = StructureChecker()
    checker.feed(html)
    checker.close()
    failures.extend(checker.errors)
    if checker.stack:
        failures.append(f"存在未闭合标签: {checker.stack}")

    # 4. 数量校验
    expect_counts = {
        "svg": 9,            # logo + 搜索 + 层级 + 锁 + 大宋大图 + 6 张卡片迷你K线 = 10? 见下
        "dynasty-card": 6,
        "tab": 2,
    }
    # 重新精确计数 svg：logo(1)+search(1)+层级(1)+锁(1)+大宋(1)+卡片(6) = 11
    svg_expected = 11
    if checker.counts["svg"] != svg_expected:
        failures.append(f"SVG 数量不符：期望 {svg_expected}，实际 {checker.counts['svg']}")
    if checker.counts["dynasty-card"] != expect_counts["dynasty-card"]:
        failures.append(f"王朝卡片数量不符：期望 6，实际 {checker.counts['dynasty-card']}")
    if checker.counts["tab"] != expect_counts["tab"]:
        failures.append(f"导航 Tab 数量不符：期望 2，实际 {checker.counts['tab']}")
    chip_active = html.count('class="chip active"')
    if chip_active != 1:
        failures.append(f"二级导航选中芯片应恰为 1 个，实际 {chip_active}")

    if failures:
        print("测试未通过：")
        for f in failures:
            print(f"  [FAIL] {f}")
        return 1

    print(f"[PASS] {TARGET.name}：结构完整，标签配对正确，"
          f"SVG={checker.counts['svg']} 卡片={checker.counts['dynasty-card']} "
          f"Tab={checker.counts['tab']} 选中芯片=1")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
