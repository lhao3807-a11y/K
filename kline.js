/* ============================================================
 * K 线引擎 · window.KLINE
 * ------------------------------------------------------------
 * 王朝国运指数与人物气运指数 **共用** 本文件，严禁在页面里再抄一份：
 * 首页迷你图、王朝盘面页、人物盘面页三处数字对不上，历史上就是算法分叉造成的。
 *
 * 与后端 database/kline.py 逐位一致，任何改动必须同步：
 *   - open = 首年取锚点首值，其余取上一年 close（**未取整**）
 *   - close = 锚点 smoothstep 插值 × (1 ± 1.5% 噪声) × (见顶年 ×1.07) × (1 + 事件冲击)
 *   - 事件冲击：bull +档位 / bear -档位 / vol 当年+半档次年-半档（巨6% 大4% 中2.5% 小2%）
 *   - high/low 取 open/close 极值（收盘价 K 线，影线不额外外扩）
 *   - 年份序列跳过 0 年（公元前 1 年之后是公元 1 年）
 * ============================================================ */
(function (root) {
  var PEAK_BOOST = 1.07;   // 见顶年冲高系数
  var NOISE = 0.03;        // 噪声幅度（±1.5%）

  // 事件冲击档位系数（下限须 > 噪声上限 1.5%，保证 bull/bear 方向确定）
  var MAG_RANK = { '巨': 4, '大': 3, '中': 2, '小': 1 };
  var EVENT_COEF = { '巨': 0.06, '大': 0.04, '中': 0.025, '小': 0.02 };

  /** 事件表 -> {year: bump}；同年多事件取档位最高的一条；vol 当年+半档、次年-半档 */
  function eventBumps(events) {
    var best = {};
    (events || []).forEach(function (ev) {
      var y = +ev.year, d = ev.dir, mag = ev.mag || '';
      var rank = MAG_RANK[mag.slice(1)] || 0;
      if (!best[y] || rank > best[y].r) best[y] = { r: rank, d: d, mag: mag };
    });
    var bumps = {};
    Object.keys(best).forEach(function (k) {
      var y = +k, it = best[k];
      var c = EVENT_COEF[it.mag.slice(1)] || EVENT_COEF['小'];
      if (it.d === 'bull') bumps[y] = (bumps[y] || 0) + c;
      else if (it.d === 'bear') bumps[y] = (bumps[y] || 0) - c;
      else if (it.d === 'vol') {
        bumps[y] = (bumps[y] || 0) + c / 2;
        var ny = nextYear(y);
        bumps[ny] = (bumps[ny] || 0) - c / 2;
      }
    });
    return bumps;
  }

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function round1(x) { return Math.round(x * 10) / 10; }

  function interpOn(list, y) {
    if (y <= list[0][0]) return list[0][1];
    for (var i = 0; i < list.length - 1; i++) {
      var a = list[i], b = list[i + 1];
      if (y >= a[0] && y <= b[0]) {
        var t = (y - a[0]) / (b[0] - a[0]);
        t = t * t * (3 - 2 * t);
        return a[1] + (b[1] - a[1]) * t;
      }
    }
    return list[list.length - 1][1];
  }

  function nextYear(y) { return y === -1 ? 1 : y + 1; }

  /** 年份序列（数字），跳过 0 年 */
  function yearsOf(start, end) {
    var out = [], y = start;
    while (y <= end) { out.push(y); y = nextYear(y); }
    return out;
  }

  /**
   * 生成年 K。o = {start, end, peak, seed, anchors, events}
   * anchors: [[year, value], ...] 按年份升序
   * events:  [{year, dir, mag}, ...]（事件冲击，可选）
   * 返回 [[open, close, low, high], ...]
   */
  function buildCandles(o) {
    var anchors = o.anchors, start = o.start, end = o.end, peak = o.peak;
    var rand = mulberry32(o.seed);
    var bumps = eventBumps(o.events);
    var out = [], prevClose = anchors[0][1];
    for (var y = start; y <= end; y = nextYear(y)) {
      var target = interpOn(anchors, y);
      var open = y === start ? anchors[0][1] : prevClose;
      var close = target * (1 + (rand() - 0.5) * NOISE)
        * (y === peak ? PEAK_BOOST : 1) * (1 + (bumps[y] || 0));
      out.push([round1(open), round1(close),
                round1(Math.min(open, close)), round1(Math.max(open, close))]);
      prevClose = close;
    }
    return out;
  }

  /**
   * 按区间把年 K 聚合成大 K（皇帝 K / 人生阶段 K）。
   * years: 数字年份数组（与 candles 一一对应）
   * spans: [{s, e}, ...]
   * 返回 [[open, close, low, high], ...]，open=区间首年开盘，close=区间末年收盘
   */
  function aggregate(candles, years, spans) {
    var idx = {};
    years.forEach(function (y, i) { idx[y] = i; });
    return spans.map(function (sp) {
      var hi = -Infinity, lo = Infinity, o = 0, c = 0;
      for (var y = sp.s; y <= sp.e; y = nextYear(y)) {
        var k = candles[idx[y]];
        if (y === sp.s) o = k[0];
        c = k[1];
        if (k[3] > hi) hi = k[3];
        if (k[2] < lo) lo = k[2];
      }
      return [round1(o), round1(c), round1(lo), round1(hi)];
    });
  }

  /** 常用统计：终值 / 最高 / 最低 / 涨跌幅 / 最大回撤 */
  function stats(candles, issue) {
    issue = issue == null ? 100 : issue;
    var last = candles[candles.length - 1][1];
    var hi = -Infinity, lo = Infinity, peak = 0, dd = 0;
    candles.forEach(function (k) {
      if (k[3] > hi) hi = k[3];
      if (k[2] < lo) lo = k[2];
      if (k[3] > peak) peak = k[3];
      var d = (k[2] - peak) / peak * 100;
      if (d < dd) dd = d;
    });
    return { last: last, high: hi, low: lo,
             chg: (last - issue) / issue * 100, maxDrawdown: dd };
  }

  root.KLINE = {
    PEAK_BOOST: PEAK_BOOST, NOISE: NOISE,
    MAG_RANK: MAG_RANK, EVENT_COEF: EVENT_COEF,
    mulberry32: mulberry32, round1: round1, interpOn: interpOn,
    eventBumps: eventBumps, nextYear: nextYear, yearsOf: yearsOf,
    buildCandles: buildCandles, aggregate: aggregate, stats: stats,
  };
})(typeof window !== 'undefined' ? window : globalThis);
