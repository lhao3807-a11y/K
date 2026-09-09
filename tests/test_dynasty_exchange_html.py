# -*- coding: utf-8 -*-
"""dynasty-exchange.html 结构校验测试（纯标准库，无需安装依赖）。

新 UI（浅色极简风）结构基线：
  黑色导航(logo+搜索) / Hero / 市场概览条 / 焦点行情 / 王朝卡片×6 / 人物预告 / 页脚

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
            "nav-link": 0,
        }

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "svg":
            self.counts["svg"] += 1
        if "chip" in classes:
            self.counts["chip"] += 1
        if "dynasty-card" in classes:
            self.counts["dynasty-card"] += 1
        if "nav-link" in classes:
            self.counts["nav-link"] += 1
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
        ("DYNASTY EXCHANGE", "品牌英文"),
        ("把五千年，看成一条 K 线。", "Hero 主标题"),
        ("进入行情", "主 CTA"),
        ("了解玩法", "次 CTA"),
        ("交易中", "市场状态"),
        ("搜索王朝", "搜索占位"),
        ("挂牌王朝", "概览-挂牌"),
        ("国运综合指数", "概览-指数"),
        ("上涨家数", "概览-上涨"),
        ("下跌家数", "概览-下跌"),
        ("大事记收录", "概览-大事记"),
        ("焦点行情", "焦点区标签"),
        ("大宋王朝", "焦点王朝"),
        ("DASONG.960", "大宋代码"),
        ("查看详情", "焦点区按钮"),
        ("王朝行情", "列表标题"),
        ('data-filter="up"', "筛选-上涨"),
        ('data-filter="down"', "筛选-下跌"),
        ('data-filter="unified"', "筛选-大一统"),
        ('data-filter="split"', "筛选-分裂期"),
        ("大秦王朝", "列表卡-秦"),
        ("大汉王朝", "列表卡-汉"),
        ("大唐王朝", "列表卡-唐"),
        ("大明王朝", "列表卡-明"),
        ("大清王朝", "列表卡-清"),
        ("人物板块", "人物预告"),
        ("即将上线", "预告徽标"),
        ("预约上线提醒", "预告按钮"),
        ("不构成投资建议", "页脚免责"),
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
    # svg：logo(1) + 搜索(1) + 焦点K线(1) + 卡片迷你走势(6) = 9
    svg_expected = 9
    if checker.counts["svg"] != svg_expected:
        failures.append(f"SVG 数量不符：期望 {svg_expected}，实际 {checker.counts['svg']}")
    if checker.counts["dynasty-card"] != 6:
        failures.append(f"王朝卡片数量不符：期望 6，实际 {checker.counts['dynasty-card']}")
    if checker.counts["nav-link"] != 4:
        failures.append(f"导航链接数量不符：期望 4，实际 {checker.counts['nav-link']}")
    if checker.counts["chip"] != 5:
        failures.append(f"筛选 chips 数量不符：期望 5，实际 {checker.counts['chip']}")
    chip_active = html.count('class="chip active"')
    if chip_active != 1:
        failures.append(f"筛选 chips 选中态应恰为 1 个，实际 {chip_active}")

    if failures:
        print("测试未通过：")
        for f in failures:
            print(f"  [FAIL] {f}")
        return 1

    print(f"[PASS] {TARGET.name}：结构完整，标签配对正确，"
          f"SVG={checker.counts['svg']} 卡片={checker.counts['dynasty-card']} "
          f"导航链接={checker.counts['nav-link']} chips={checker.counts['chip']} 选中=1")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
