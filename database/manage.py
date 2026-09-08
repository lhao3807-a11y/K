# -*- coding: utf-8 -*-
"""
王朝K线图 · 数据库管理工具
========================
以 SQLite（database/dynasty.db）为唯一数据源，导出 data.js 供 index.html 读取。

常用命令：
  python database/manage.py init                 # 建库 + 导入种子数据（--force 重建）
  python database/manage.py export               # 导出 ../data.js（--out 指定路径）
  python database/manage.py show                 # 概览：王朝信息 + 各表统计
  python database/manage.py validate             # 数据一致性校验（导出前自动执行）

事件 CRUD：
  python database/manage.py event list [--year 960]
  python database/manage.py event add --year 1189 --title "..." --term "..." \
         --dir bull --mag "+中" --desc "..."
  python database/manage.py event update 3 --title "..." --dir bear
  python database/manage.py event delete 3

皇帝 CRUD：  emperor list|add|update|delete（字段 --name --full --start --end）
锚点 CRUD：  anchor list|add|update|delete（字段 --year --value）
配置：       config list | config set span_full 100
王朝参数：   dynasty show | dynasty update --peak-year 1082 --issue-price 100
"""
import argparse
import json
import os
import re
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "dynasty.db")
SCHEMA = os.path.join(BASE_DIR, "schema.sql")
PROJECT_DIR = os.path.dirname(BASE_DIR)
DEFAULT_OUT = os.path.join(PROJECT_DIR, "data.js")

DIRS = ("bull", "bear", "vol", "neutral")
MAG_RE = re.compile(r"^[+±-][大小中巨]$")

# ---------------- 种子数据（与原 index.html 完全一致，一一对应） ----------------

SEED_DYNASTY = dict(
    code="DASONG.960", name="大宋王朝",
    range_label="960 — 1279 · 国运指数 · 年 K / 皇帝 K",
    start_year=960, end_year=1279, issue_price=100,
    peak_year=1082, seed=9601279, is_active=1,
    notes="国运指数为叙事化演绎，非真实历史数据 · 事件线索参考《上下五千年》",
)

SEED_EMPERORS = [  # (name, full, s, e)
    ("太祖", "宋太祖 赵匡胤", 960, 976), ("太宗", "宋太宗 赵匡义", 977, 997),
    ("真宗", "宋真宗 赵恒", 998, 1022), ("仁宗", "宋仁宗 赵祯", 1023, 1063),
    ("英宗", "宋英宗 赵曙", 1064, 1067), ("神宗", "宋神宗 赵顼", 1068, 1085),
    ("哲宗", "宋哲宗 赵煦", 1086, 1100), ("徽宗", "宋徽宗 赵佶", 1101, 1125),
    ("钦宗", "宋钦宗 赵桓", 1126, 1127), ("高宗", "宋高宗 赵构", 1128, 1161),
    ("孝宗", "宋孝宗 赵昚", 1162, 1189), ("光宗", "宋光宗 赵惇", 1190, 1194),
    ("宁宗", "宋宁宗 赵扩", 1195, 1224), ("理宗", "宋理宗 赵昀", 1225, 1264),
    ("度宗", "宋度宗 赵禥", 1265, 1274), ("恭帝", "宋恭帝 赵㬎", 1275, 1276),
    ("端宗", "宋端宗 赵昰", 1277, 1278), ("末帝", "宋末帝 赵昺", 1279, 1279),
]

SEED_EVENTS = [  # (year, title, term, dir, mag, desc)
    (960, "陈桥兵变 · 黄袍加身", "IPO 上市", "bull", "+大",
     "赵匡胤黄袍加身，代周建宋，国运指数以发行价 100 点挂牌上市。"),
    (979, "灭北汉 · 完成统一", "跳空高开", "bull", "+大",
     "太宗灭北汉，中原基本归一，市场情绪亢奋，指数追高超买。"),
    (980, "高粱河惨败 · 太宗飙驴车", "闪崩", "bear", "-大",
     "攻辽于高粱河大败，太宗股中两箭、乘驴车南逃，指数重挫。（史实为 979 年，为避让上方标注顺移一年）"),
    (1004, "澶州之战 · 真宗亲征", "绝地反击", "bull", "+大",
     "辽军大举南下，王钦若主张迁都避敌；寇准力促真宗亲征，澶州城下床子弩射杀辽帅萧挞凛，士气大振，指数绝地反击。"),
    (1005, "澶渊之盟 · 岁币换和平", "利好出尽", "bear", "-中",
     "宋辽约为兄弟之国，换来百年和平，但岁输银十万两、绢二十万匹，长期负担落地，和平红利兑现后指数回吐。"),
    (1043, "庆历新政 · 范仲淹", "改革题材", "vol", "±小",
     "范仲淹推行新政，整顿吏治触动既得利益，改革题材炒作，波动加大。"),
    (1069, "王安石变法 · 熙宁新法", "多空拉锯", "vol", "±中",
     "熙宁变法历时十余年，新旧党争反复拉锯，指数高波动、方向不明。"),
    (1082, "永乐城之败 · 神宗痛哭", "见顶回落", "bear", "-大",
     "大举攻西夏永乐城惨败，士卒伤亡数十万，神宗临朝痛哭，变法成果受挫。国运指数于此见顶，由盛转衰。"),
    (1102, "徽宗即位 · 蔡京专权", "趋势反转", "bear", "-中",
     "徽宗即位，起用蔡京，立元祐党籍碑、兴花石纲，朝政日坏，指数自高位趋势反转、步入长期下行。"),
    (1127, "靖康之变 · 二帝北狩", "闪崩 -50%", "bear", "-巨",
     "金兵攻破汴京，徽、钦二帝被掳北去，北宋就此退市，指数腰斩。"),
    (1128, "南宋建立 · 偏安临安", "借壳重组", "neutral", "+小",
     "赵构南渡称帝，南宋重新挂牌，缩量企稳，进入下半场。"),
    (1140, "岳飞北伐 · 郾城大捷", "强势反弹", "bull", "+大",
     "岳家军连败金军，兵锋直指故都，指数走出最强劲一波反弹。"),
    (1141, "绍兴和议 · 岳飞冤死", "利空落地", "bear", "-中",
     "十二道金牌召回，岳飞以\u201c莫须有\u201d遇害，纳贡称臣，指数回吐。"),
    (1162, "孝宗即位 · 隆兴北伐", "题材反弹", "bull", "+小",
     "孝宗锐意恢复，为岳飞平反，隆兴北伐先胜后败，指数小幅冲高。"),
    (1187, "乾淳之治 · 南宋鼎盛", "慢牛 · 黄金顶", "bull", "+中",
     "孝宗乾道、淳熙年间南宋鼎盛，经济文化繁荣，指数创历史高位区。"),
    (1206, "开禧北伐 · 韩侂胄冒进", "冲高回落", "bear", "-中",
     "韩侂胄仓促发动开禧北伐，全线溃败，指数冲高回落。"),
    (1234, "联蒙灭金 · 引狼入室", "利好出尽", "bear", "-中",
     "与蒙古联手灭金，端平入洛惨败，唇亡齿寒，蒙古旋即大举南侵。"),
    (1259, "钓鱼城 · 击毙蒙哥", "超跌反弹", "bull", "+小",
     "合州钓鱼城下蒙哥汗殒命，蒙古暂缓南下，指数短线反弹。"),
    (1273, "襄阳失守 · 门户洞开", "破位下跌", "bear", "-大",
     "襄樊坚守六年终告陷落，长江门户洞开，指数破位下行。"),
    (1276, "临安陷落 · 恭帝出降", "加速赶底", "bear", "-大",
     "元军入临安，恭帝出降，太皇太后奉玺请降，指数加速探底。"),
    (1279, "崖山海战 · 负帝投海", "摘牌退市", "bear", "-巨",
     "崖山海战宋军覆灭，陆秀夫负幼帝赵昺投海，宋朝摘牌退市，指数归零。"),
]

SEED_ANCHORS = [
    (960, 100), (979, 135), (980, 112), (1000, 124), (1003, 112), (1004, 138),
    (1005, 126), (1022, 146), (1043, 178), (1069, 186), (1082, 222), (1085, 204),
    (1100, 168), (1124, 150), (1126, 70), (1130, 90), (1140, 118), (1142, 96),
    (1165, 150), (1187, 165), (1207, 128), (1234, 112), (1259, 120), (1272, 100),
    (1273, 58), (1276, 26), (1279, 2),
]

SEED_CONFIG = [
    ("span_full", "120", "年K标注详略阈值：缩放跨度<=该年数展开完整标注"),
    ("ma_year", "20", "年K均线周期（MA20）"),
    ("ma_emperor", "3", "皇帝K均线周期（MA3）"),
]

# ---------------- 基础工具 ----------------


def out(s=""):
    print(s)


def connect(db_path=DEFAULT_DB):
    if not os.path.exists(db_path):
        sys.exit(f"[x] 数据库不存在：{db_path}，请先执行 init")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_active(conn):
    row = conn.execute(
        "SELECT * FROM dynasties WHERE is_active=1 ORDER BY id LIMIT 1").fetchone()
    if row is None:
        sys.exit("[x] 无 active 王朝记录")
    return row


def fail(msg):
    sys.exit(f"[x] {msg}")


def ok(msg):
    print(f"[ok] {msg}")


def validate_event(dyn, year, dir_, mag):
    if not (dyn["start_year"] <= year <= dyn["end_year"]):
        fail(f"事件年份 {year} 超出王朝区间 [{dyn['start_year']}, {dyn['end_year']}]")
    if dir_ not in DIRS:
        fail(f"dir 必须是 {'/'.join(DIRS)} 之一，收到：{dir_}")
    if not MAG_RE.match(mag or ""):
        fail(f"mag 格式应为 [+-±][大小中巨]，如 +大 / -中 / ±小，收到：{mag}")


def validate_emperor(conn, dyn, start, end, exclude_id=None):
    if start > end:
        fail(f"在位区间非法：{start} > {end}")
    if not (dyn["start_year"] <= start and end <= dyn["end_year"]):
        fail(f"在位区间 [{start}, {end}] 超出王朝区间 [{dyn['start_year']}, {dyn['end_year']}]")
    sql = ("SELECT name, start_year, end_year FROM emperors WHERE dynasty_id=? AND id != ?")
    for r in conn.execute(sql, (dyn["id"], exclude_id or -1)):
        if start <= r["end_year"] and end >= r["start_year"]:
            fail(f"与 {r['name']}（{r['start_year']}–{r['end_year']}）在位区间重叠")


def check_coverage(conn, dyn):
    """皇帝在位区间须无缝覆盖王朝起止年。"""
    rows = conn.execute(
        "SELECT start_year, end_year FROM emperors WHERE dynasty_id=? ORDER BY start_year",
        (dyn["id"],)).fetchall()
    problems = []
    if not rows:
        problems.append("无皇帝记录")
    else:
        cur = dyn["start_year"]
        for r in rows:
            if r["start_year"] != cur:
                problems.append(f"区间断裂：期望从 {cur} 开始，实际 {r['start_year']}")
            cur = r["end_year"] + 1
        if cur != dyn["end_year"] + 1:
            problems.append(f"区间未覆盖到 {dyn['end_year']}（止于 {cur-1}）")
    return problems


# ---------------- 子命令：init / export / show / validate ----------------


def cmd_init(args):
    if os.path.exists(args.db):
        if not args.force:
            fail(f"数据库已存在：{args.db}（--force 重建）")
        os.remove(args.db)
    conn = sqlite3.connect(args.db)
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    cur = conn.execute(
        "INSERT INTO dynasties(code,name,range_label,start_year,end_year,issue_price,"
        "peak_year,seed,is_active,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (SEED_DYNASTY["code"], SEED_DYNASTY["name"], SEED_DYNASTY["range_label"],
         SEED_DYNASTY["start_year"], SEED_DYNASTY["end_year"], SEED_DYNASTY["issue_price"],
         SEED_DYNASTY["peak_year"], SEED_DYNASTY["seed"], 1, SEED_DYNASTY["notes"]))
    did = cur.lastrowid
    conn.executemany(
        "INSERT INTO emperors(dynasty_id,name,full_name,start_year,end_year,sort) "
        "VALUES(?,?,?,?,?,?)",
        [(did, n, f, s, e, i) for i, (n, f, s, e) in enumerate(SEED_EMPERORS)])
    conn.executemany(
        "INSERT INTO events(dynasty_id,year,title,term,dir,mag,description,sort) "
        "VALUES(?,?,?,?,?,?,?,?)",
        [(did, y, t, m, d, g, ds, i) for i, (y, t, m, d, g, ds) in enumerate(SEED_EVENTS)])
    conn.executemany(
        "INSERT INTO anchors(dynasty_id,year,value,sort) VALUES(?,?,?,?)",
        [(did, y, v, i) for i, (y, v) in enumerate(SEED_ANCHORS)])
    conn.executemany("INSERT INTO config(key,value,notes) VALUES(?,?,?)", SEED_CONFIG)
    conn.commit()
    conn.close()
    ok(f"数据库已初始化：{args.db}")
    ok(f"导入：皇帝 {len(SEED_EMPERORS)} 条 / 事件 {len(SEED_EVENTS)} 条 / "
       f"锚点 {len(SEED_ANCHORS)} 条 / 配置 {len(SEED_CONFIG)} 条")
    cmd_export(argparse.Namespace(db=args.db, out=DEFAULT_OUT))


def cmd_validate(args):
    conn = connect(args.db)
    dyn = get_active(conn)
    problems = []
    problems += check_coverage(conn, dyn)
    for r in conn.execute("SELECT id,year,title FROM events WHERE dynasty_id=?", (dyn["id"],)):
        if not (dyn["start_year"] <= r["year"] <= dyn["end_year"]):
            problems.append(f"事件「{r['title']}」年份 {r['year']} 超出王朝区间")
    for r in conn.execute("SELECT year,value FROM anchors WHERE dynasty_id=? ORDER BY sort",
                          (dyn["id"],)):
        if not (dyn["start_year"] <= r["year"] <= dyn["end_year"]):
            problems.append(f"锚点年份 {r['year']} 超出王朝区间")
    conn.close()
    if problems:
        for p in problems:
            print(f"  [!] {p}")
        fail(f"校验未通过，共 {len(problems)} 个问题")
    ok("校验通过：皇帝区间无缝覆盖、事件/锚点年份均在王朝区间内")


def cmd_export(args):
    conn = connect(args.db)
    dyn = get_active(conn)
    problems = check_coverage(conn, dyn)
    conn.close()
    if problems:
        for p in problems:
            print(f"  [!] {p}")
        fail("导出中止：皇帝在位区间未无缝覆盖王朝起止年（用 validate 查看详情）")
    conn = connect(args.db)
    emps = [{"name": r["name"], "full": r["full_name"], "s": r["start_year"], "e": r["end_year"]}
            for r in conn.execute(
                "SELECT name,full_name,start_year,end_year FROM emperors "
                "WHERE dynasty_id=? ORDER BY sort", (dyn["id"],))]
    evs = [{"year": r["year"], "title": r["title"], "term": r["term"], "dir": r["dir"],
            "mag": r["mag"], "desc": r["description"]}
           for r in conn.execute(
               "SELECT year,title,term,dir,mag,description FROM events "
               "WHERE dynasty_id=? ORDER BY sort", (dyn["id"],))]
    anchors = [[r["year"], r["value"]] for r in conn.execute(
        "SELECT year,value FROM anchors WHERE dynasty_id=? ORDER BY sort", (dyn["id"],))]
    cfg = {r["key"]: (int(r["value"]) if r["value"].lstrip("-").isdigit() else
                      float(r["value"]) if re.match(r"^-?\d+\.\d+$", r["value"]) else r["value"])
           for r in conn.execute("SELECT key,value FROM config")}
    conn.close()

    data = {
        "dynasty": {
            "code": dyn["code"], "name": dyn["name"], "rangeLabel": dyn["range_label"],
            "startYear": dyn["start_year"], "endYear": dyn["end_year"],
            "issuePrice": dyn["issue_price"], "peakYear": dyn["peak_year"], "seed": dyn["seed"],
        },
        "emperors": emps, "events": evs, "anchors": anchors, "config": cfg,
    }
    body = json.dumps(data, ensure_ascii=False, indent=2)
    header = ("// 自动生成：python database/manage.py export（数据源 database/dynasty.db）\n"
              "// 请勿手改本文件，修改请编辑数据库后重新导出\n")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(header + "window.DYNASTY_DATA = " + body + ";\n")
    ok(f"已导出 {args.out}：皇帝 {len(emps)} / 事件 {len(evs)} / 锚点 {len(anchors)}")


def cmd_show(args):
    conn = connect(args.db)
    dyn = get_active(conn)
    out(f"王朝：{dyn['name']}（{dyn['code']}）")
    out(f"  区间 {dyn['start_year']}–{dyn['end_year']} · 发行价 {dyn['issue_price']} · "
        f"见顶年 {dyn['peak_year']} · 种子 {dyn['seed']}")
    for t in ("emperors", "events", "anchors"):
        n = conn.execute(f"SELECT COUNT(*) c FROM {t} WHERE dynasty_id=?",
                         (dyn["id"],)).fetchone()["c"]
        out(f"  {t:<10} {n} 条")
    out("  config:")
    for r in conn.execute("SELECT key,value FROM config"):
        out(f"    {r['key']} = {r['value']}")
    conn.close()


# ---------------- CRUD：events ----------------


def cmd_event(args):
    conn = connect(args.db)
    dyn = get_active(conn)
    if args.action == "list":
        sql = "SELECT * FROM events WHERE dynasty_id=?"
        params = [dyn["id"]]
        if args.year:
            sql += " AND year=?"
            params.append(args.year)
        sql += " ORDER BY sort"
        for r in conn.execute(sql, params):
            out(f"  #{r['id']:<3} {r['year']}  [{r['dir']:<7} {r['mag']:<3}] "
                f"{r['title']}  ——  {r['term']}")
    elif args.action == "add":
        if args.year is None or not args.title or not args.term:
            fail("add 需要 --year --title --term（--dir --mag --desc 可选，默认 bull/+中/空）")
        year, dir_, mag = args.year, args.dir or "bull", args.mag or "+中"
        desc = args.desc or ""
        validate_event(dyn, year, dir_, mag)
        nxt = conn.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM events WHERE dynasty_id=?",
                           (dyn["id"],)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO events(dynasty_id,year,title,term,dir,mag,description,sort,notes) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (dyn["id"], year, args.title, args.term, dir_, mag, desc,
             args.sort if args.sort is not None else nxt, args.notes or ""))
        conn.commit()
        ok(f"事件已新增 id={cur.lastrowid}：{year} {args.title}")
    elif args.action == "update":
        row = conn.execute("SELECT * FROM events WHERE id=? AND dynasty_id=?",
                           (args.id, dyn["id"])).fetchone()
        if not row:
            fail(f"事件 id={args.id} 不存在")
        year = args.year if args.year is not None else row["year"]
        dir_ = args.dir or row["dir"]
        mag = args.mag or row["mag"]
        validate_event(dyn, year, dir_, mag)
        conn.execute(
            "UPDATE events SET year=?,title=?,term=?,dir=?,mag=?,description=?,notes=? WHERE id=?",
            (year, args.title or row["title"], args.term or row["term"], dir_, mag,
             args.desc if args.desc is not None else row["description"],
             args.notes if args.notes is not None else row["notes"], args.id))
        conn.commit()
        ok(f"事件 id={args.id} 已更新")
    elif args.action == "delete":
        row = conn.execute("SELECT title FROM events WHERE id=? AND dynasty_id=?",
                           (args.id, dyn["id"])).fetchone()
        if not row:
            fail(f"事件 id={args.id} 不存在")
        conn.execute("DELETE FROM events WHERE id=?", (args.id,))
        conn.commit()
        ok(f"已删除事件 id={args.id}：{row['title']}")
    conn.close()


# ---------------- CRUD：emperors ----------------


def cmd_emperor(args):
    conn = connect(args.db)
    dyn = get_active(conn)
    if args.action == "list":
        for r in conn.execute("SELECT * FROM emperors WHERE dynasty_id=? ORDER BY sort",
                              (dyn["id"],)):
            out(f"  #{r['id']:<3} {r['start_year']}–{r['end_year']}  "
                f"{r['name']}（{r['full_name']}）")
    elif args.action == "add":
        if not args.name or not args.full or args.start is None or args.end is None:
            fail("add 需要 --name --full --start --end")
        validate_emperor(conn, dyn, args.start, args.end)
        nxt = conn.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM emperors WHERE dynasty_id=?",
                           (dyn["id"],)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO emperors(dynasty_id,name,full_name,start_year,end_year,sort,notes) "
            "VALUES(?,?,?,?,?,?,?)",
            (dyn["id"], args.name, args.full, args.start, args.end,
             args.sort if args.sort is not None else nxt, args.notes or ""))
        conn.commit()
        ok(f"皇帝已新增 id={cur.lastrowid}（注意检查在位区间是否无缝覆盖：validate）")
    elif args.action == "update":
        row = conn.execute("SELECT * FROM emperors WHERE id=? AND dynasty_id=?",
                           (args.id, dyn["id"])).fetchone()
        if not row:
            fail(f"皇帝 id={args.id} 不存在")
        start = args.start if args.start is not None else row["start_year"]
        end = args.end if args.end is not None else row["end_year"]
        validate_emperor(conn, dyn, start, end, exclude_id=args.id)
        conn.execute(
            "UPDATE emperors SET name=?,full_name=?,start_year=?,end_year=?,notes=? WHERE id=?",
            (args.name or row["name"], args.full or row["full_name"], start, end,
             args.notes if args.notes is not None else row["notes"], args.id))
        conn.commit()
        ok(f"皇帝 id={args.id} 已更新")
    elif args.action == "delete":
        row = conn.execute("SELECT name FROM emperors WHERE id=? AND dynasty_id=?",
                           (args.id, dyn["id"])).fetchone()
        if not row:
            fail(f"皇帝 id={args.id} 不存在")
        conn.execute("DELETE FROM emperors WHERE id=?", (args.id,))
        conn.commit()
        ok(f"已删除皇帝 id={args.id}：{row['name']}（注意检查区间覆盖：validate）")
    conn.close()


# ---------------- CRUD：anchors ----------------


def cmd_anchor(args):
    conn = connect(args.db)
    dyn = get_active(conn)
    if args.action == "list":
        for r in conn.execute("SELECT * FROM anchors WHERE dynasty_id=? ORDER BY sort",
                              (dyn["id"],)):
            out(f"  #{r['id']:<3} {r['year']}  ->  {r['value']}")
    elif args.action == "add":
        if args.year is None or args.value is None:
            fail("add 需要 --year --value")
        if not (dyn["start_year"] <= args.year <= dyn["end_year"]):
            fail(f"锚点年份 {args.year} 超出王朝区间")
        nxt = conn.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM anchors WHERE dynasty_id=?",
                           (dyn["id"],)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO anchors(dynasty_id,year,value,sort,notes) VALUES(?,?,?,?,?)",
            (dyn["id"], args.year, args.value,
             args.sort if args.sort is not None else nxt, args.notes or ""))
        conn.commit()
        ok(f"锚点已新增 id={cur.lastrowid}：{args.year} -> {args.value}（注意保持年份升序）")
    elif args.action == "update":
        row = conn.execute("SELECT * FROM anchors WHERE id=? AND dynasty_id=?",
                           (args.id, dyn["id"])).fetchone()
        if not row:
            fail(f"锚点 id={args.id} 不存在")
        conn.execute("UPDATE anchors SET year=?,value=?,notes=? WHERE id=?",
                     (args.year if args.year is not None else row["year"],
                      args.value if args.value is not None else row["value"],
                      args.notes if args.notes is not None else row["notes"], args.id))
        conn.commit()
        ok(f"锚点 id={args.id} 已更新")
    elif args.action == "delete":
        row = conn.execute("SELECT year,value FROM anchors WHERE id=? AND dynasty_id=?",
                           (args.id, dyn["id"])).fetchone()
        if not row:
            fail(f"锚点 id={args.id} 不存在")
        conn.execute("DELETE FROM anchors WHERE id=?", (args.id,))
        conn.commit()
        ok(f"已删除锚点 id={args.id}：{row['year']} -> {row['value']}")
    conn.close()


# ---------------- config / dynasty ----------------


def cmd_config(args):
    conn = connect(args.db)
    if args.action == "list":
        for r in conn.execute("SELECT key,value,notes FROM config"):
            out(f"  {r['key']:<12} = {r['value']:<8} # {r['notes']}")
    elif args.action == "set":
        cur = conn.execute("UPDATE config SET value=? WHERE key=?", (args.value, args.key))
        if cur.rowcount == 0:
            conn.execute("INSERT INTO config(key,value,notes) VALUES(?,?,'')",
                         (args.key, args.value))
        conn.commit()
        ok(f"config.{args.key} = {args.value}")
    conn.close()


def cmd_dynasty(args):
    conn = connect(args.db)
    dyn = get_active(conn)
    if args.action == "show":
        for k in dyn.keys():
            if k not in ("id",):
                out(f"  {k:<12} = {dyn[k]}")
        return
    sets, vals = [], []
    mapping = {"name": "name", "code": "code", "range_label": "range_label",
               "start_year": "start_year", "end_year": "end_year",
               "issue_price": "issue_price", "peak_year": "peak_year", "seed": "seed"}
    for arg, col in mapping.items():
        v = getattr(args, arg, None)
        if v is not None:
            sets.append(f"{col}=?")
            vals.append(v)
    if not sets:
        fail("update 至少需要一个字段，如 --peak-year 1082")
    if args.start_year is not None or args.end_year is not None:
        s = args.start_year if args.start_year is not None else dyn["start_year"]
        e = args.end_year if args.end_year is not None else dyn["end_year"]
        if s > e:
            fail("起始年不能晚于结束年")
    sets.append("updated_at=datetime('now','localtime')")
    conn.execute(f"UPDATE dynasties SET {', '.join(sets)} WHERE id=?", vals + [dyn["id"]])
    conn.commit()
    ok("王朝参数已更新（如改了起止年，请运行 validate 检查区间覆盖）")
    conn.close()


# ---------------- 参数解析 ----------------


def add_event_p(sp):
    sp.add_argument("--year", type=int)
    sp.add_argument("--title")
    sp.add_argument("--term")
    sp.add_argument("--dir", choices=DIRS)
    sp.add_argument("--mag", help="冲击幅度，如 +大 / -中 / ±小；"
                                  "负号开头的值请用等号写法 --mag=-中")
    sp.add_argument("--desc")
    sp.add_argument("--sort", type=int)
    sp.add_argument("--notes")


def add_emperor_p(sp):
    sp.add_argument("--name")
    sp.add_argument("--full")
    sp.add_argument("--start", type=int)
    sp.add_argument("--end", type=int)
    sp.add_argument("--sort", type=int)
    sp.add_argument("--notes")


def add_anchor_p(sp):
    sp.add_argument("--year", type=int)
    sp.add_argument("--value", type=float)
    sp.add_argument("--sort", type=int)
    sp.add_argument("--notes")


def build_parser():
    p = argparse.ArgumentParser(description="王朝K线图数据库管理工具")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite 数据库路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="建库并导入种子数据")
    sp.add_argument("--force", action="store_true", help="覆盖已有数据库")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("export", help="导出 data.js")
    sp.add_argument("--out", default=DEFAULT_OUT)
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("show", help="概览")
    sp.set_defaults(fn=cmd_show)

    sp = sub.add_parser("validate", help="数据一致性校验")
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser("event", help="事件 CRUD")
    es = sp.add_subparsers(dest="action", required=True)
    s = es.add_parser("list"); s.add_argument("--year", type=int); s.set_defaults(fn=cmd_event)
    s = es.add_parser("add"); add_event_p(s); s.set_defaults(fn=cmd_event)
    s = es.add_parser("update"); s.add_argument("id", type=int); add_event_p(s)
    s.set_defaults(fn=cmd_event)
    s = es.add_parser("delete"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_event)

    sp = sub.add_parser("emperor", help="皇帝 CRUD")
    es = sp.add_subparsers(dest="action", required=True)
    s = es.add_parser("list"); s.set_defaults(fn=cmd_emperor)
    s = es.add_parser("add"); add_emperor_p(s); s.set_defaults(fn=cmd_emperor)
    s = es.add_parser("update"); s.add_argument("id", type=int); add_emperor_p(s)
    s.set_defaults(fn=cmd_emperor)
    s = es.add_parser("delete"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_emperor)

    sp = sub.add_parser("anchor", help="锚点 CRUD")
    es = sp.add_subparsers(dest="action", required=True)
    s = es.add_parser("list"); s.set_defaults(fn=cmd_anchor)
    s = es.add_parser("add"); add_anchor_p(s); s.set_defaults(fn=cmd_anchor)
    s = es.add_parser("update"); s.add_argument("id", type=int); add_anchor_p(s)
    s.set_defaults(fn=cmd_anchor)
    s = es.add_parser("delete"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_anchor)

    sp = sub.add_parser("config", help="展示参数")
    es = sp.add_subparsers(dest="action", required=True)
    s = es.add_parser("list"); s.set_defaults(fn=cmd_config)
    s = es.add_parser("set"); s.add_argument("key"); s.add_argument("value")
    s.set_defaults(fn=cmd_config)

    sp = sub.add_parser("dynasty", help="王朝参数")
    es = sp.add_subparsers(dest="action", required=True)
    s = es.add_parser("show"); s.set_defaults(fn=cmd_dynasty)
    s = es.add_parser("update")
    s.add_argument("--name"); s.add_argument("--code"); s.add_argument("--range-label",
                                                                     dest="range_label")
    s.add_argument("--start-year", type=int, dest="start_year")
    s.add_argument("--end-year", type=int, dest="end_year")
    s.add_argument("--issue-price", type=float, dest="issue_price")
    s.add_argument("--peak-year", type=int, dest="peak_year")
    s.add_argument("--seed", type=int)
    s.set_defaults(fn=cmd_dynasty)
    return p


if __name__ == "__main__":
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = build_parser().parse_args()
    args.fn(args)
