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
