-- ============================================================
-- 王朝K线图 · 后端数据库 Schema（与前端 index.html 字段一一对应）
--
-- 表结构映射：
--   dynasties  -> 头部标题栏（代码/名称/区间）+ 生成参数（发行价/见顶年/随机种子）
--   emperors   -> 前端 EMPERORS：{name, full, s(起始年), e(结束年)}
--   events     -> 前端 EVENTS：{year, title, term, dir, mag, desc}
--   anchors    -> 前端 ANCHORS：[year, value] 锚点序列
--   config     -> 前端展示参数：span_full / ma_year / ma_emperor 等
--
-- 多王朝拓展：events/emperors/anchors 均含 dynasty_id 外键，
--             dynasties.is_active 标记当前导出到 data.js 的王朝。
--
-- 使用：python database/manage.py init   建库并导入种子数据
--       python database/manage.py export 生成 ../data.js
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dynasties (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  code         TEXT NOT NULL UNIQUE,          -- 证券代码，如 DASONG.960
  name         TEXT NOT NULL,                 -- 名称，如 大宋王朝
  range_label  TEXT NOT NULL DEFAULT '',      -- 区间文案，如 960 — 1279 · 国运指数 · 年 K / 皇帝 K
  start_year   INTEGER NOT NULL,              -- 指数起始年（对应前端 START）
  end_year     INTEGER NOT NULL,              -- 指数结束年（对应前端 END）
  issue_price  REAL NOT NULL DEFAULT 100,     -- 发行价（对应前端 ISSUE，默认 100）
  peak_year    INTEGER,                       -- 见顶年（对应前端 PEAK，如 1082 永乐城之败）
  seed         INTEGER NOT NULL DEFAULT 9601279,  -- K线随机种子 mulberry32 参数
  is_active    INTEGER NOT NULL DEFAULT 1,    -- 1=导出到 data.js 的当前王朝
  notes        TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS emperors (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  dynasty_id   INTEGER NOT NULL REFERENCES dynasties(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,                 -- 庙号简称，如 太祖
  full_name    TEXT NOT NULL,                 -- 全称，如 宋太祖 赵匡胤（前端 full）
  start_year   INTEGER NOT NULL,              -- 在位起始年（前端 s，含）
  end_year     INTEGER NOT NULL,              -- 在位结束年（前端 e，含）
  sort         INTEGER NOT NULL DEFAULT 0,    -- 排序（时间序）
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  dynasty_id   INTEGER NOT NULL REFERENCES dynasties(id) ON DELETE CASCADE,
  year         INTEGER NOT NULL,              -- 事件年份
  title        TEXT NOT NULL,                 -- 事件标题，如 陈桥兵变 · 黄袍加身
  term         TEXT NOT NULL,                 -- 金融术语，如 IPO 上市
  dir          TEXT NOT NULL CHECK (dir IN ('bull','bear','vol','neutral')),
  mag          TEXT NOT NULL,                 -- 冲击幅度：+大/-中/±小 等
  description  TEXT NOT NULL DEFAULT '',      -- 事件描述（前端 desc）
  sort         INTEGER NOT NULL DEFAULT 0,    -- 排序（时间序）
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS anchors (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  dynasty_id   INTEGER NOT NULL REFERENCES dynasties(id) ON DELETE CASCADE,
  year         INTEGER NOT NULL,              -- 锚点年份
  value        REAL NOT NULL,                 -- 国运指数目标值
  sort         INTEGER NOT NULL DEFAULT 0,    -- 排序（年份升序）
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS config (
  key          TEXT PRIMARY KEY,              -- 如 span_full / ma_year / ma_emperor
  value        TEXT NOT NULL,
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_emperors_dyn ON emperors(dynasty_id, sort);
CREATE INDEX IF NOT EXISTS idx_events_dyn   ON events(dynasty_id, sort);
CREATE INDEX IF NOT EXISTS idx_anchors_dyn  ON anchors(dynasty_id, sort);

-- ============================================================
-- 人物板块（与王朝板块同构：年 K + 阶段 K，共用同一套 K 线算法）
--
--   figures         -> 人物主表（对标 dynasties）
--   figure_periods  -> 人生阶段（对标 emperors，区间须无缝覆盖）
--   figure_events   -> 生平事迹（对标 events，多 quote 诗句列）
--   figure_anchors  -> 气运指数锚点（对标 anchors）
--
-- 说明：人物与王朝分表而治，因为人物事件带诗句引用与维度标签、
--       阶段带一句话主题，塞进王朝表会长出恒为 NULL 的列。
--       K 线算法本身物理复用 database/kline.py，两板块不会分叉。
-- ============================================================

CREATE TABLE IF NOT EXISTS figures (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  code         TEXT NOT NULL UNIQUE,          -- 证券代码，如 LIBAI.701
  name         TEXT NOT NULL,                 -- 姓名，如 李白
  alias        TEXT NOT NULL DEFAULT '',      -- 字号，如 字太白 · 号青莲居士
  role         TEXT NOT NULL DEFAULT '',      -- 身份，如 诗人 / 帝王 / 名将
  range_label  TEXT NOT NULL DEFAULT '',      -- 区间文案，如 701 — 762 · 气运指数 · 年 K / 阶段 K
  start_year   INTEGER NOT NULL,              -- 指数起始年（出生年）
  end_year     INTEGER NOT NULL,              -- 指数结束年（去世年）
  issue_price  REAL NOT NULL DEFAULT 100,     -- 发行价（默认 100）
  peak_year    INTEGER,                       -- 见顶年（如 742 奉诏入京）
  seed         INTEGER NOT NULL DEFAULT 701762,   -- K线随机种子
  dynasty_code TEXT NOT NULL DEFAULT '',      -- 所属王朝代码（如 TANG.618，供联动）
  summary      TEXT NOT NULL DEFAULT '',      -- 一句话简介
  is_active    INTEGER NOT NULL DEFAULT 0,    -- 1=默认展示的人物
  notes        TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS figure_periods (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  figure_id    INTEGER NOT NULL REFERENCES figures(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,                 -- 阶段名，如 供奉翰林
  theme        TEXT NOT NULL DEFAULT '',      -- 一句话主题，如 仰天大笑出门去
  start_year   INTEGER NOT NULL,              -- 阶段起始年（含）
  end_year     INTEGER NOT NULL,              -- 阶段结束年（含）
  sort         INTEGER NOT NULL DEFAULT 0,
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS figure_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  figure_id    INTEGER NOT NULL REFERENCES figures(id) ON DELETE CASCADE,
  year         INTEGER NOT NULL,              -- 事件年份
  title        TEXT NOT NULL,                 -- 事件标题
  term         TEXT NOT NULL,                 -- 金融术语，如 一字涨停
  dir          TEXT NOT NULL CHECK (dir IN ('bull','bear','vol','neutral')),
  mag          TEXT NOT NULL,                 -- 冲击幅度：+大/-中/±小 等
  description  TEXT NOT NULL DEFAULT '',      -- 事件描述
  quote        TEXT NOT NULL DEFAULT '',      -- 诗句 / 史料原文佐证
  sort         INTEGER NOT NULL DEFAULT 0,
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS figure_anchors (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  figure_id    INTEGER NOT NULL REFERENCES figures(id) ON DELETE CASCADE,
  year         INTEGER NOT NULL,
  value        REAL NOT NULL,                 -- 气运指数目标值
  sort         INTEGER NOT NULL DEFAULT 0,
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_fig_periods ON figure_periods(figure_id, sort);
CREATE INDEX IF NOT EXISTS idx_fig_events  ON figure_events(figure_id, sort);
CREATE INDEX IF NOT EXISTS idx_fig_anchors ON figure_anchors(figure_id, sort);
