/* ==========================================================================
   交易很轻松 · Canvas K线引擎（零依赖）
   单画布绘制：主图(K线+均线+BOLL+缠论笔/中枢+买卖点+筹码区) / 成交量 / 副图
   支持：滚轮缩放、拖动平移、十字光标、双击复位
   ========================================================================== */
(function (global) {
  'use strict';

  var C = {
    up: '#ef232a', down: '#14b143', flat: '#8a8a8a',
    grid: '#f0f2f4', grid2: '#e4e7eb',
    text: '#8d949c', text2: '#555b62', text1: '#1a1a1a',
    axis: '#e4e7eb',
    ma5: '#f5a623', ma10: '#4a90e2', ma20: '#9b51e0', ma60: '#2ecc71', ma120: '#7f8c8d',
    boll: '#8fa9c9',
    bi: '#e6a23c', zs: 'rgba(230,162,60,0.10)', zsLine: '#e6a23c',
    mainZone: 'rgba(255,143,31,0.13)', mainZoneLine: 'rgba(255,143,31,0.55)',
    retailZone: 'rgba(59,130,246,0.11)', retailZoneLine: 'rgba(59,130,246,0.5)',
    mainCost: '#ff8f1f', retailCost: '#3b82f6',
    cross: '#5a6470',
    dif: '#f5a623', dea: '#4a90e2',
    k: '#f5a623', d: '#4a90e2', j: '#9b51e0',
  };

  var FONT = '11px -apple-system,"PingFang SC","Microsoft YaHei",Arial,sans-serif';
  var FONT_B = '600 11px -apple-system,"PingFang SC","Microsoft YaHei",Arial,sans-serif';

  function fmtPrice(p) {
    if (p == null || isNaN(p)) return '—';
    var a = Math.abs(p);
    if (a >= 1000) return p.toFixed(2);
    if (a >= 100) return p.toFixed(2);
    if (a >= 10) return p.toFixed(2);
    if (a >= 1) return p.toFixed(3);
    return p.toFixed(4);
  }

  function fmtVol(v) {
    if (v == null || isNaN(v)) return '—';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
    if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
    return String(Math.round(v));
  }

  function fmtDate(d, minute) {
    if (!d) return '';
    if (minute) return d.slice(11, 16) || d.slice(5);
    return d.slice(5);
  }

  function KLineChart(canvas, tipEl) {
    this.cv = canvas;
    this.ctx = canvas.getContext('2d');
    this.tip = tipEl;
    this.bars = [];
    this.ind = {};
    this.chan = null;
    this.chip = null;
    this.turning = null;
    this.opts = { ma: true, boll: false, chan: true, chip: true, sig: true, sub: 'macd', nav: false };
    this.count = 120;
    this.end = 0;
    this.cross = null;
    this.drag = null;
    this.W = 0; this.H = 0;
    this._bind();
  }

  KLineChart.prototype.setData = function (d) {
    var keepCount = this.count, keepEnd = this.end;
    this.bars = (d && d.bars) || [];
    this.ind = (d && d.ind) || {};
    this.chan = (d && d.chan) || null;
    this.chip = (d && d.chip) || null;
    this.turning = (d && d.turning) || null;
    this.opts.nav = !!(d && d.navMode);
    if (!this.bars.length) { this.end = 0; return; }
    if (keepEnd && keepEnd > 0 && this.end !== 0) {
      this.count = Math.min(keepCount, this.bars.length);
      this.end = Math.min(keepEnd, this.bars.length);
    } else {
      this.count = Math.min(120, this.bars.length);
      this.end = this.bars.length;
    }
    this._clamp();
  };

  KLineChart.prototype.setOption = function (k, v) {
    this.opts[k] = v;
    this.draw();
  };

  KLineChart.prototype._clamp = function () {
    var n = this.bars.length;
    this.count = Math.max(20, Math.min(this.count, n));
    this.end = Math.max(this.count, Math.min(this.end, n));
  };

  KLineChart.prototype.resize = function () {
    var rect = this.cv.getBoundingClientRect();
    var dpr = global.devicePixelRatio || 1;
    if (rect.width < 10 || rect.height < 10) return false;
    this.W = rect.width;
    this.H = rect.height;
    this.cv.width = Math.round(rect.width * dpr);
    this.cv.height = Math.round(rect.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return true;
  };

  KLineChart.prototype._layout = function () {
    var padL = 6, padR = 66, padT = 8, padB = 20;
    var totalH = this.H - padT - padB;
    var subH = Math.max(50, totalH * 0.18);
    var volH = Math.max(38, totalH * 0.12);
    var mainH = totalH - subH - volH - 14;
    return {
      padL: padL, padR: padR, padT: padT, padB: padB,
      plotW: this.W - padL - padR,
      mainTop: padT, mainH: mainH, mainBottom: padT + mainH,
      volTop: padT + mainH + 8, volH: volH, volBottom: padT + mainH + 8 + volH,
      subTop: padT + mainH + 8 + volH + 6, subH: subH,
      subBottom: padT + mainH + 8 + volH + 6 + subH,
    };
  };

  KLineChart.prototype.draw = function () {
    if (!this.resize()) return;
    var ctx = this.ctx;
    ctx.clearRect(0, 0, this.W, this.H);
    if (!this.bars.length) {
      ctx.fillStyle = C.text;
      ctx.font = FONT;
      ctx.textAlign = 'center';
      ctx.fillText('暂无K线数据', this.W / 2, this.H / 2);
      return;
    }
    var L = this._layout();
    this.L = L;
    var s = this.end - this.count;
    var e = this.end;
    this.s = s; this.e = e;
    var n = this.count;
    this.barW = L.plotW / n;

    // ---- 价格范围
    var hi = -Infinity, lo = Infinity;
    for (var i = s; i < e; i++) {
      var b = this.bars[i];
      if (!b) continue;
      if (b.h > hi) hi = b.h;
      if (b.l < lo) lo = b.l;
      if (this.opts.ma) {
        ['ma5', 'ma10', 'ma20', 'ma60'].forEach(function (k) {
          var v = this.ind[k] && this.ind[k][i];
          if (v != null) { if (v > hi) hi = v; if (v < lo) lo = v; }
        }, this);
      }
      if (this.opts.boll) {
        ['boll_up', 'boll_low'].forEach(function (k) {
          var v = this.ind[k] && this.ind[k][i];
          if (v != null) { if (v > hi) hi = v; if (v < lo) lo = v; }
        }, this);
      }
    }
    if (!isFinite(hi) || !isFinite(lo)) { return; }
    var pad = (hi - lo) * 0.06 || hi * 0.01;
    hi += pad; lo -= pad;
    this.pHi = hi; this.pLo = lo;

    this._drawGrid(L);
    if (this.opts.chip) this._drawChipZones(L);
    this._drawCandles(L);
    if (this.opts.boll) this._drawBoll(L);
    if (this.opts.ma) this._drawMA(L);
    if (this.opts.chan && this.chan) this._drawChan(L);
    if (this.opts.sig && this.chan) this._drawSignals(L);
    if (this.opts.chan && this.turning) this._drawTurns(L);
    this._drawPriceAxis(L);
    this._drawVol(L);
    this._drawSub(L);
    this._drawTimeAxis(L);
    if (this.cross) this._drawCross(L);
  };

  // ------------------------------------------------------------ 坐标
  KLineChart.prototype._px = function (i) {
    return this.L.padL + (i - this.s + 0.5) * this.barW;
  };
  KLineChart.prototype._py = function (p) {
    var L = this.L;
    return L.mainTop + (this.pHi - p) / (this.pHi - this.pLo) * L.mainH;
  };

  // ------------------------------------------------------------ 网格
  KLineChart.prototype._drawGrid = function (L) {
    var ctx = this.ctx;
    ctx.save();
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    ctx.font = FONT;
    var steps = 5;
    for (var k = 0; k <= steps; k++) {
      var y = L.mainTop + L.mainH * k / steps;
      ctx.beginPath();
      ctx.moveTo(L.padL, Math.round(y) + 0.5);
      ctx.lineTo(L.padL + L.plotW, Math.round(y) + 0.5);
      ctx.stroke();
    }
    // 竖向网格
    var vs = 6;
    for (var v = 0; v <= vs; v++) {
      var x = L.padL + L.plotW * v / vs;
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, L.mainTop);
      ctx.lineTo(Math.round(x) + 0.5, L.mainBottom);
      ctx.stroke();
    }
    // 副图分隔
    ctx.strokeStyle = C.grid2;
    [L.volTop - 4, L.subTop - 3].forEach(function (y) {
      ctx.beginPath();
      ctx.moveTo(L.padL, Math.round(y) + 0.5);
      ctx.lineTo(L.padL + L.plotW, Math.round(y) + 0.5);
      ctx.stroke();
    });
    ctx.restore();
  };

  // ------------------------------------------------------------ 筹码区
  KLineChart.prototype._drawChipZones = function (L) {
    var cp = this.chip;
    if (!cp || !cp.ok) return;
    var ctx = this.ctx;
    ctx.save();
    ctx.beginPath();
    ctx.rect(L.padL, L.mainTop, L.plotW, L.mainH);
    ctx.clip();

    function band(z, fill, line) {
      if (!z) return;
      var y1 = this._py(z.high), y2 = this._py(z.low);
      if (y2 < y1) { var t = y1; y1 = y2; y2 = t; }
      if (y2 < L.mainTop || y1 > L.mainBottom) return;
      var cy1 = Math.max(y1, L.mainTop), cy2 = Math.min(y2, L.mainBottom);
      ctx.fillStyle = fill;
      ctx.fillRect(L.padL, cy1, L.plotW, Math.max(1, cy2 - cy1));
      ctx.strokeStyle = line;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(L.padL, y1 + 0.5); ctx.lineTo(L.padL + L.plotW, y1 + 0.5);
      ctx.moveTo(L.padL, y2 + 0.5); ctx.lineTo(L.padL + L.plotW, y2 + 0.5);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    band.call(this, cp.main_zone, C.mainZone, C.mainZoneLine);
    band.call(this, cp.retail_zone, C.retailZone, C.retailZoneLine);

    function costLine(p, color, dash, label) {
      if (!p) return;
      var y = this._py(p);
      if (y < L.mainTop + 2 || y > L.mainBottom - 2) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.moveTo(L.padL, y + 0.5);
      ctx.lineTo(L.padL + L.plotW, y + 0.5);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = FONT;
      ctx.textAlign = 'left';
      ctx.fillStyle = 'rgba(255,255,255,.82)';
      var tw = ctx.measureText(label).width;
      ctx.fillRect(L.padL + L.plotW - tw - 8, y - 12, tw + 6, 12);
      ctx.fillStyle = color;
      ctx.fillText(label, L.padL + L.plotW - tw - 5, y - 2);
    }
    costLine.call(this, cp.main_cost, C.mainCost, [6, 4], '主力成本 ' + fmtPrice(cp.main_cost));
    costLine.call(this, cp.retail_cost, C.retailCost, [2, 3], '散户成本 ' + fmtPrice(cp.retail_cost));
    if (cp.vp && cp.vp.poc) {
      costLine.call(this, cp.vp.poc, '#9b51e0', [1, 3], 'POC ' + fmtPrice(cp.vp.poc));
    }

    // 现价线
    var last = this.bars[this.bars.length - 1];
    if (last) {
      var y = this._py(last.c);
      ctx.strokeStyle = last.c >= last.o ? 'rgba(239,35,42,.5)' : 'rgba(20,177,67,.5)';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(L.padL, y + 0.5);
      ctx.lineTo(L.padL + L.plotW, y + 0.5);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.restore();

    this._drawChipInfo(L, cp);
  };

  // 左上角筹码信息块（不受裁剪限制，始终可见）
  KLineChart.prototype._drawChipInfo = function (L, cp) {
    var ctx = this.ctx;
    var px = this.bars[this.bars.length - 1].c;
    var d1 = (cp.main_cost / px - 1) * 100;
    var d2 = (cp.retail_cost / px - 1) * 100;
    var txt1 = '主力成本 ' + fmtPrice(cp.main_cost) + ' ' + (d1 >= 0 ? '+' : '') + d1.toFixed(1) + '%';
    var txt2 = '散户成本 ' + fmtPrice(cp.retail_cost) + ' ' + (d2 >= 0 ? '+' : '') + d2.toFixed(1) + '%';
    var txt3 = '控盘 ' + cp.control.toFixed(0) + '% · 获利 ' + cp.profit_ratio.toFixed(0) +
      '% · 集中度 ' + (cp.concentration * 100).toFixed(1);

    ctx.save();
    ctx.font = FONT_B;
    var w1 = ctx.measureText(txt1).width;
    var w2 = ctx.measureText(txt2).width;
    var boxW = w1 + w2 + 26;
    var boxH = 32;
    ctx.fillStyle = 'rgba(255,255,255,.86)';
    ctx.strokeStyle = '#eef1f4';
    ctx.lineWidth = 1;
    this._roundRect(L.padL + 5, L.mainTop + 4, boxW, boxH, 3);
    ctx.fill();
    ctx.stroke();

    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = C.mainCost;
    ctx.fillText(txt1, L.padL + 11, L.mainTop + 14);
    ctx.fillStyle = C.retailCost;
    ctx.fillText(txt2, L.padL + 11 + w1 + 14, L.mainTop + 14);
    ctx.font = FONT;
    ctx.fillStyle = '#8d949c';
    ctx.fillText(txt3, L.padL + 11, L.mainTop + 28);
    ctx.restore();
  };

  KLineChart.prototype._roundRect = function (x, y, w, h, r) {
    var ctx = this.ctx;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  };

  // ------------------------------------------------------------ K线
  KLineChart.prototype._drawCandles = function (L) {
    var ctx = this.ctx;
    if (this.opts.nav) { this._drawNavLine(L); return; }
    var bw = Math.max(1, this.barW * 0.72);
    var half = Math.max(0.5, bw / 2);
    ctx.save();
    for (var i = this.s; i < this.e; i++) {
      var b = this.bars[i];
      if (!b) continue;
      var x = this._px(i);
      var up = b.c >= b.o;
      var color = up ? C.up : C.down;
      var yO = this._py(b.o), yC = this._py(b.c);
      var yH = this._py(b.h), yL = this._py(b.l);
      var top = Math.min(yO, yC), hgt = Math.max(1, Math.abs(yC - yO));

      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 1;
      // 影线
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, yH);
      ctx.lineTo(Math.round(x) + 0.5, yL);
      ctx.stroke();
      // 实体
      if (up && bw > 2.5) {
        ctx.fillStyle = '#fff';
        ctx.fillRect(Math.round(x - half) + 0.5, Math.round(top) + 0.5, Math.round(bw) - 1, Math.round(hgt) - 1);
        ctx.strokeRect(Math.round(x - half) + 0.5, Math.round(top) + 0.5, Math.round(bw) - 1, Math.round(hgt) - 1);
      } else {
        ctx.fillRect(Math.round(x - half), Math.round(top), Math.max(1, Math.round(bw)), Math.max(1, Math.round(hgt)));
      }
    }
    ctx.restore();
  };

  // 场外基金净值：折线 + 渐变面积
  KLineChart.prototype._drawNavLine = function (L) {
    var ctx = this.ctx;
    var pts = [];
    for (var i = this.s; i < this.e; i++) {
      var b = this.bars[i];
      if (!b) continue;
      pts.push([this._px(i), this._py(b.c)]);
    }
    if (pts.length < 2) return;
    var last = this.bars[this.e - 1], first = this.bars[this.s];
    var up = last.c >= first.c;
    var col = up ? C.up : C.down;

    ctx.save();
    var g = ctx.createLinearGradient(0, L.mainTop, 0, L.mainBottom);
    g.addColorStop(0, up ? 'rgba(239,35,42,.22)' : 'rgba(20,177,67,.22)');
    g.addColorStop(1, up ? 'rgba(239,35,42,.01)' : 'rgba(20,177,67,.01)');
    ctx.beginPath();
    ctx.moveTo(pts[0][0], L.mainBottom);
    pts.forEach(function (p) { ctx.lineTo(p[0], p[1]); });
    ctx.lineTo(pts[pts.length - 1][0], L.mainBottom);
    ctx.closePath();
    ctx.fillStyle = g;
    ctx.fill();

    ctx.beginPath();
    pts.forEach(function (p, k) { k ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); });
    ctx.strokeStyle = col;
    ctx.lineWidth = 1.6;
    ctx.lineJoin = 'round';
    ctx.stroke();
    ctx.restore();
  };

  // ------------------------------------------------------------ 均线
  KLineChart.prototype._drawMA = function (L) {
    var ctx = this.ctx;
    var defs = [['ma5', C.ma5], ['ma10', C.ma10], ['ma20', C.ma20], ['ma60', C.ma60]];
    ctx.save();
    ctx.lineWidth = 1.2;
    ctx.lineJoin = 'round';
    for (var d = 0; d < defs.length; d++) {
      var arr = this.ind[defs[d][0]];
      if (!arr) continue;
      ctx.strokeStyle = defs[d][1];
      ctx.beginPath();
      var started = false;
      for (var i = this.s; i < this.e; i++) {
        var v = arr[i];
        if (v == null) { started = false; continue; }
        var x = this._px(i), y = this._py(v);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.restore();
  };

  // ------------------------------------------------------------ BOLL
  KLineChart.prototype._drawBoll = function (L) {
    var ctx = this.ctx;
    ctx.save();
    ctx.lineWidth = 1;
    ctx.strokeStyle = C.boll;
    ['boll_up', 'boll_mid', 'boll_low'].forEach(function (k, idx) {
      var arr = this.ind[k];
      if (!arr) return;
      ctx.setLineDash(idx === 1 ? [] : [4, 3]);
      ctx.beginPath();
      var started = false;
      for (var i = this.s; i < this.e; i++) {
        var v = arr[i];
        if (v == null) { started = false; continue; }
        var x = this._px(i), y = this._py(v);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }, this);
    ctx.setLineDash([]);
    ctx.restore();
  };

  // ------------------------------------------------------------ 缠论
  KLineChart.prototype._drawChan = function (L) {
    var ch = this.chan;
    var ctx = this.ctx;
    ctx.save();

    // 中枢矩形
    (ch.zhongshu || []).forEach(function (z) {
      if (z.e < this.s || z.s > this.e) return;
      var x1 = this._px(Math.max(z.s, this.s)) - this.barW / 2;
      var x2 = this._px(Math.min(z.e, this.e)) + this.barW / 2;
      var y1 = this._py(z.zg), y2 = this._py(z.zd);
      ctx.fillStyle = C.zs;
      ctx.fillRect(x1, y1, Math.max(2, x2 - x1), Math.max(1, y2 - y1));
      ctx.strokeStyle = C.zsLine;
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = 1;
      ctx.strokeRect(x1 + 0.5, y1 + 0.5, Math.max(1, x2 - x1) - 1, Math.max(1, y2 - y1) - 1);
      ctx.globalAlpha = 1;
      // ZG/ZD 标注
      if (x2 - x1 > 40) {
        ctx.font = FONT;
        ctx.fillStyle = C.zsLine;
        ctx.textAlign = 'left';
        ctx.fillText('ZG ' + fmtPrice(z.zg), x1 + 4, y1 - 3);
        ctx.fillText('ZD ' + fmtPrice(z.zd), x1 + 4, y2 + 11);
      }
    }, this);

    // 笔
    var bis = ch.bis || [];
    ctx.strokeStyle = C.bi;
    ctx.lineWidth = 1.4;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    var started = false;
    for (var k = 0; k < bis.length; k++) {
      var b = bis[k];
      if (b.e < this.s - 1 || b.s > this.e) { started = false; continue; }
      var x1 = this._px(b.s), y1 = this._py(b.sp);
      var x2 = this._px(b.e), y2 = this._py(b.ep);
      if (!started) { ctx.moveTo(x1, y1); started = true; }
      else ctx.lineTo(x1, y1);
      ctx.lineTo(x2, y2);
    }
    ctx.stroke();
    ctx.restore();
  };

  // ------------------------------------------------------------ 买卖点
  KLineChart.prototype._drawSignals = function (L) {
    var ctx = this.ctx;
    var sigs = (this.chan && this.chan.signals) || [];
    ctx.save();
    ctx.font = FONT_B;
    sigs.forEach(function (sg) {
      if (sg.i < this.s || sg.i >= this.e) return;
      var x = this._px(sg.i);
      var y = this._py(sg.p);
      var isBuy = sg.side === 'buy';
      var color = isBuy ? C.up : C.down;
      var dir = isBuy ? 1 : -1;
      var off = isBuy ? 14 : -14;
      // 三角
      ctx.fillStyle = color;
      ctx.beginPath();
      if (isBuy) {
        ctx.moveTo(x, y + 6);
        ctx.lineTo(x - 5, y + 13);
        ctx.lineTo(x + 5, y + 13);
      } else {
        ctx.moveTo(x, y - 6);
        ctx.lineTo(x - 5, y - 13);
        ctx.lineTo(x + 5, y - 13);
      }
      ctx.closePath();
      ctx.fill();
      // 文字
      var label = sg.t;
      var tw = ctx.measureText(label).width;
      var ly = y + off + (isBuy ? 12 : 0);
      if (ly > L.mainBottom - 2) ly = L.mainBottom - 2;
      if (ly < L.mainTop + 10) ly = L.mainTop + 10;
      ctx.fillStyle = 'rgba(255,255,255,.9)';
      ctx.fillRect(x - tw / 2 - 3, ly - 9, tw + 6, 12);
      ctx.fillStyle = color;
      ctx.textAlign = 'center';
      ctx.fillText(label, x, ly);
    }, this);
    ctx.restore();
  };

  // ------------------------------------------------------------ 转折点（事后确认）
  //
  // 与缠论买卖点区分开：这里画的是「事后被 PS 算法确认的拐点」，
  // 用空心圆环 + 顶/底小字，实心三角留给缠论，避免两套信号混在一起看不清。
  KLineChart.prototype._drawTurns = function (L) {
    var ctx = this.ctx;
    var tv = this.turning;
    if (!tv || !tv.turns || !tv.turns.length) return;
    ctx.save();
    ctx.font = '9px -apple-system,"Microsoft YaHei",sans-serif';
    ctx.textAlign = 'center';
    tv.turns.forEach(function (t) {
      if (t.i < this.s || t.i >= this.e) return;
      var x = this._px(t.i);
      var y = this._py(t.p);
      var isTop = t.t === 'top';
      var color = isTop ? C.down : C.up;
      // 先铺白底，避免圆环压在密集 K 线上看不清
      ctx.beginPath();
      ctx.arc(x, y, 7, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,.82)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
      var ly = isTop ? y - 10 : y + 17;
      if (ly < L.mainTop + 10) ly = L.mainTop + 10;
      if (ly > L.mainBottom - 2) ly = L.mainBottom - 2;
      var txt = isTop ? '顶' : '底';
      var tw = ctx.measureText(txt).width;
      ctx.fillStyle = 'rgba(255,255,255,.9)';
      ctx.fillRect(x - tw / 2 - 2, ly - 8, tw + 4, 10);
      ctx.fillStyle = color;
      ctx.fillText(txt, x, ly);
    }, this);
    ctx.restore();
  };

  // ------------------------------------------------------------ 价格轴
  KLineChart.prototype._drawPriceAxis = function (L) {
    var ctx = this.ctx;
    ctx.save();
    ctx.fillStyle = '#fff';
    ctx.fillRect(L.padL + L.plotW, L.mainTop, L.padR, L.mainH + 2);
    ctx.strokeStyle = C.axis;
    ctx.beginPath();
    ctx.moveTo(L.padL + L.plotW + 0.5, L.mainTop);
    ctx.lineTo(L.padL + L.plotW + 0.5, L.mainBottom);
    ctx.stroke();

    ctx.textBaseline = 'middle';
    var steps = 5;
    for (var k = 0; k <= steps; k++) {
      var y = L.mainTop + L.mainH * k / steps;
      var p = this.pHi - (this.pHi - this.pLo) * k / steps;
      ctx.font = FONT;
      ctx.textAlign = 'left';
      ctx.fillStyle = C.text;
      ctx.fillText(fmtPrice(p), L.padL + L.plotW + 6, y);
      ctx.strokeStyle = C.axis;
      ctx.beginPath();
      ctx.moveTo(L.padL + L.plotW, Math.round(y) + 0.5);
      ctx.lineTo(L.padL + L.plotW + 4, Math.round(y) + 0.5);
      ctx.stroke();
    }

    // 涨跌幅信息放左上角，右侧只留价格轴
    var first = this.bars[this.s];
    if (first) {
      var lastb = this.bars[this.e - 1];
      var chgv = (lastb.c / first.c - 1) * 100;
      ctx.font = FONT_B;
      ctx.textAlign = 'left';
      ctx.fillStyle = chgv >= 0 ? 'rgba(239,35,42,.85)' : 'rgba(20,177,67,.85)';
      ctx.fillText('区间 ' + (chgv >= 0 ? '+' : '') + chgv.toFixed(2) + '%',
        L.padL + 6, L.mainTop + L.mainH - 6);
    }
    ctx.restore();
  };

  // ------------------------------------------------------------ 成交量
  KLineChart.prototype._drawVol = function (L) {
    var ctx = this.ctx;
    var mx = 0;
    for (var i = this.s; i < this.e; i++) {
      var b = this.bars[i];
      if (b && b.v > mx) mx = b.v;
    }
    if (mx <= 0) { this._drawVolAxisEmpty(L); return; }
    var bw = Math.max(1, this.barW * 0.72);
    ctx.save();
    for (var j = this.s; j < this.e; j++) {
      var bar = this.bars[j];
      if (!bar) continue;
      var h = bar.v / mx * (L.volH - 6);
      var x = this._px(j);
      ctx.fillStyle = bar.c >= bar.o ? C.up : C.down;
      ctx.globalAlpha = bar.c >= bar.o ? 0.85 : 0.85;
      ctx.fillRect(x - bw / 2, L.volTop + L.volH - h, bw, h);
    }
    ctx.globalAlpha = 1;
    // 均量线
    var vma = this.ind.vr;
    ctx.restore();

    ctx.save();
    ctx.font = FONT;
    ctx.textAlign = 'left';
    ctx.fillStyle = C.text;
    ctx.fillText('成交量 ' + fmtVol(this.bars[this.e - 1] ? this.bars[this.e - 1].v : 0), L.padL + 4, L.volTop + 9);
    ctx.textAlign = 'right';
    ctx.fillText('均量峰 ' + fmtVol(mx), L.padL + L.plotW - 4, L.volTop + 9);
    ctx.restore();
  };

  KLineChart.prototype._drawVolAxisEmpty = function (L) {
    var ctx = this.ctx;
    ctx.save();
    ctx.font = FONT;
    ctx.fillStyle = '#c8ced4';
    ctx.textAlign = 'left';
    ctx.fillText('无成交量数据（场外基金）', L.padL + 6, L.volTop + L.volH / 2);
    ctx.restore();
  };

  // ------------------------------------------------------------ 副图
  KLineChart.prototype._drawSub = function (L) {
    var sub = this.opts.sub;
    if (sub === 'kdj') return this._drawKDJ(L);
    if (sub === 'rsi') return this._drawRSI(L);
    return this._drawMACD(L);
  };

  KLineChart.prototype._drawMACD = function (L) {
    var ctx = this.ctx;
    var dif = this.ind.dif, dea = this.ind.dea, hist = this.ind.macd;
    if (!dif || !dea) return;
    var mx = 0;
    for (var i = this.s; i < this.e; i++) {
      [dif[i], dea[i], hist[i]].forEach(function (v) { if (v != null && Math.abs(v) > mx) mx = Math.abs(v); });
    }
    if (mx <= 0) mx = 1;
    var mid = L.subTop + L.subH / 2;
    var scale = (L.subH / 2 - 4) / mx;
    var bw = Math.max(1, this.barW * 0.6);

    ctx.save();
    // 零轴
    ctx.strokeStyle = C.grid2;
    ctx.beginPath();
    ctx.moveTo(L.padL, mid + 0.5);
    ctx.lineTo(L.padL + L.plotW, mid + 0.5);
    ctx.stroke();

    // 柱
    for (var j = this.s; j < this.e; j++) {
      var v = hist[j];
      if (v == null) continue;
      var h = Math.abs(v) * scale;
      var x = this._px(j);
      ctx.fillStyle = v >= 0 ? 'rgba(239,35,42,.75)' : 'rgba(20,177,67,.75)';
      ctx.fillRect(x - bw / 2, v >= 0 ? mid - h : mid, bw, Math.max(1, h));
    }
    // 线
    [[dif, C.dif], [dea, C.dea]].forEach(function (pair) {
      ctx.strokeStyle = pair[1];
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      var st = false;
      for (var k = this.s; k < this.e; k++) {
        var val = pair[0][k];
        if (val == null) { st = false; continue; }
        var x = this._px(k), y = mid - val * scale;
        if (!st) { ctx.moveTo(x, y); st = true; } else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }, this);

    ctx.font = FONT;
    ctx.textAlign = 'left';
    var li = this.e - 1;
    ctx.fillStyle = C.dif; ctx.fillText('DIF ' + (dif[li] == null ? '—' : dif[li].toFixed(3)), L.padL + 4, L.subTop + 10);
    ctx.fillStyle = C.dea; ctx.fillText('DEA ' + (dea[li] == null ? '—' : dea[li].toFixed(3)), L.padL + 78, L.subTop + 10);
    var hv = hist[li];
    ctx.fillStyle = hv == null ? C.text : (hv >= 0 ? C.up : C.down);
    ctx.fillText('MACD ' + (hv == null ? '—' : hv.toFixed(3)), L.padL + 152, L.subTop + 10);
    ctx.restore();
  };

  KLineChart.prototype._drawKDJ = function (L) {
    var ctx = this.ctx;
    var k = this.ind.k, d = this.ind.d, j = this.ind.j;
    if (!k || !d) return;
    var top = L.subTop, h = L.subH;
    function y(v) { return top + h - (Math.max(-20, Math.min(120, v)) / 140) * h; }
    ctx.save();
    ctx.strokeStyle = C.grid2;
    [20, 50, 80].forEach(function (v) {
      ctx.beginPath();
      ctx.moveTo(L.padL, y(v) + 0.5);
      ctx.lineTo(L.padL + L.plotW, y(v) + 0.5);
      ctx.stroke();
    });
    [[k, C.k], [d, C.d], [j, C.j]].forEach(function (pair) {
      ctx.strokeStyle = pair[1];
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      var st = false;
      for (var i = this.s; i < this.e; i++) {
        var v = pair[0][i];
        if (v == null) { st = false; continue; }
        var x = this._px(i);
        if (!st) { ctx.moveTo(x, y(v)); st = true; } else ctx.lineTo(x, y(v));
      }
      ctx.stroke();
    }, this);
    ctx.font = FONT;
    ctx.textAlign = 'left';
    var li = this.e - 1;
    ctx.fillStyle = C.k; ctx.fillText('K ' + (k[li] == null ? '—' : k[li].toFixed(1)), L.padL + 4, top + 10);
    ctx.fillStyle = C.d; ctx.fillText('D ' + (d[li] == null ? '—' : d[li].toFixed(1)), L.padL + 64, top + 10);
    ctx.fillStyle = C.j; ctx.fillText('J ' + (j[li] == null ? '—' : j[li].toFixed(1)), L.padL + 124, top + 10);
    ctx.restore();
  };

  KLineChart.prototype._drawRSI = function (L) {
    var ctx = this.ctx;
    var arr = this.ind.rsi14;
    if (!arr) return;
    var top = L.subTop, h = L.subH;
    function y(v) { return top + h - (v / 100) * h; }
    ctx.save();
    ctx.strokeStyle = C.grid2;
    [30, 50, 70].forEach(function (v) {
      ctx.beginPath();
      ctx.moveTo(L.padL, y(v) + 0.5);
      ctx.lineTo(L.padL + L.plotW, y(v) + 0.5);
      ctx.stroke();
    });
    ctx.strokeStyle = C.ma20;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    var st = false;
    for (var i = this.s; i < this.e; i++) {
      var v = arr[i];
      if (v == null) { st = false; continue; }
      var x = this._px(i);
      if (!st) { ctx.moveTo(x, y(v)); st = true; } else ctx.lineTo(x, y(v));
    }
    ctx.stroke();
    ctx.font = FONT;
    ctx.fillStyle = C.ma20;
    ctx.textAlign = 'left';
    var li = this.e - 1;
    ctx.fillText('RSI14 ' + (arr[li] == null ? '—' : arr[li].toFixed(1)), L.padL + 4, top + 10);
    ctx.restore();
  };

  // ------------------------------------------------------------ 时间轴
  KLineChart.prototype._drawTimeAxis = function (L) {
    var ctx = this.ctx;
    ctx.save();
    ctx.font = FONT;
    ctx.fillStyle = C.text;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    var minute = (this.bars[this.s] && this.bars[this.s].d || '').length > 10;
    var want = Math.max(3, Math.floor(L.plotW / 92));
    var step = Math.max(1, Math.floor(this.count / want));
    for (var i = this.s; i < this.e; i += step) {
      var b = this.bars[i];
      if (!b) continue;
      var x = this._px(i);
      if (x < L.padL + 16 || x > L.padL + L.plotW - 16) continue;
      ctx.fillText(fmtDate(b.d, minute), x, L.subBottom + 5);
    }
    ctx.restore();
  };

  // ------------------------------------------------------------ 十字光标
  KLineChart.prototype._drawCross = function (L) {
    var ctx = this.ctx;
    var cr = this.cross;
    if (!cr) return;
    var i = Math.round(this.s + (cr.x - L.padL) / this.barW - 0.5);
    if (i < this.s) i = this.s;
    if (i >= this.e) i = this.e - 1;
    var b = this.bars[i];
    if (!b) return;
    var x = this._px(i);
    var y = cr.y;
    ctx.save();
    ctx.strokeStyle = C.cross;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x + 0.5, L.mainTop);
    ctx.lineTo(x + 0.5, L.subBottom);
    ctx.stroke();
    if (y > L.mainTop && y < L.mainBottom) {
      ctx.beginPath();
      ctx.moveTo(L.padL, y + 0.5);
      ctx.lineTo(L.padL + L.plotW, y + 0.5);
      ctx.stroke();
      // 价格标签
      var p = this.pHi - (y - L.mainTop) / L.mainH * (this.pHi - this.pLo);
      ctx.setLineDash([]);
      ctx.fillStyle = '#3d4650';
      var txt = fmtPrice(p);
      var tw = ctx.measureText(txt).width + 10;
      ctx.fillRect(L.padL + L.plotW + 1, y - 8, tw, 16);
      ctx.fillStyle = '#fff';
      ctx.font = FONT;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(txt, L.padL + L.plotW + 6, y);
    }
    // 时间标签
    ctx.setLineDash([]);
    var dtxt = b.d.length > 10 ? b.d : b.d;
    var dw = ctx.measureText(dtxt).width + 10;
    ctx.fillStyle = '#3d4650';
    ctx.fillRect(x - dw / 2, L.subBottom + 2, dw, 15);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = FONT;
    ctx.fillText(dtxt, x, L.subBottom + 10);
    ctx.restore();
  };

  // ------------------------------------------------------------ 交互
  KLineChart.prototype._bind = function () {
    var self = this;
    var cv = this.cv;

    function pos(ev) {
      var r = cv.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    }

    cv.addEventListener('mousemove', function (ev) {
      var p = pos(ev);
      if (self.drag) {
        var dx = p.x - self.drag.x;
        var shift = Math.round(dx / self.barW);
        if (shift !== 0) {
          self.end = Math.max(self.count, Math.min(self.bars.length, self.drag.end - shift));
          self.drag.x = p.x;
          self.drag.end = self.end;
          self.draw();
        }
        return;
      }
      self.cross = p;
      self.draw();
      self._showTip(p);
    });

    cv.addEventListener('mouseleave', function () {
      self.cross = null;
      self.drag = null;
      if (self.tip) self.tip.style.display = 'none';
      self.draw();
    });

    cv.addEventListener('mousedown', function (ev) {
      if (ev.button !== 0) return;
      var p = pos(ev);
      self.drag = { x: p.x, end: self.end };
      cv.style.cursor = 'grabbing';
    });

    global.addEventListener('mouseup', function () {
      if (self.drag) { self.drag = null; cv.style.cursor = 'crosshair'; }
    });

    cv.addEventListener('wheel', function (ev) {
      ev.preventDefault();
      var dir = ev.deltaY > 0 ? 1 : -1;
      var old = self.count;
      var nc = Math.round(old * (dir > 0 ? 1.18 : 0.85));
      nc = Math.max(20, Math.min(self.bars.length, nc));
      if (nc === old) return;
      var p = pos(ev);
      var L = self._layout();
      var ratio = Math.max(0, Math.min(1, (p.x - L.padL) / L.plotW));
      var anchor = self.s + ratio * old;
      self.count = nc;
      self.end = Math.round(anchor + (1 - ratio) * nc);
      self.end = Math.max(nc, Math.min(self.bars.length, self.end));
      self.draw();
    }, { passive: false });

    cv.addEventListener('dblclick', function () {
      self.count = Math.min(120, self.bars.length);
      self.end = self.bars.length;
      self.draw();
    });
  };

  KLineChart.prototype._showTip = function (p) {
    if (!this.tip || !this.L) return;
    var L = this.L;
    if (p.x < L.padL || p.x > L.padL + L.plotW) { this.tip.style.display = 'none'; return; }
    var i = Math.round(this.s + (p.x - L.padL) / this.barW - 0.5);
    if (i < this.s || i >= this.e) { this.tip.style.display = 'none'; return; }
    var b = this.bars[i];
    if (!b) { this.tip.style.display = 'none'; return; }
    var up = b.c >= b.o;
    var pct = (b.c / b.o - 1) * 100;
    var rows = [
      ['开盘', fmtPrice(b.o)], ['最高', fmtPrice(b.h)],
      ['最低', fmtPrice(b.l)], ['收盘', fmtPrice(b.c)],
      ['涨跌', (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%'],
    ];
    if (b.v > 0) rows.push(['成交量', fmtVol(b.v)]);
    var idx = i;
    var extra = [];
    ['ma5', 'ma10', 'ma20', 'ma60'].forEach(function (k) {
      var v = this.ind[k] && this.ind[k][idx];
      if (v != null && this.opts.ma) extra.push([k.toUpperCase(), fmtPrice(v)]);
    }, this);
    var hv = this.ind.macd && this.ind.macd[idx];
    if (hv != null) extra.push(['MACD', hv.toFixed(3)]);
    var rv = this.ind.rsi14 && this.ind.rsi14[idx];
    if (rv != null) extra.push(['RSI14', rv.toFixed(1)]);

    var html = '<div class="th">' + b.d + '</div>';
    rows.concat(extra).forEach(function (r) {
      html += '<div class="tr"><span class="tk">' + r[0] + '</span><span class="tv">' + r[1] + '</span></div>';
    });
    this.tip.innerHTML = html;
    this.tip.style.display = 'block';
    var tw = this.tip.offsetWidth || 160;
    var th = this.tip.offsetHeight || 140;
    var left = p.x + 16;
    if (left + tw > this.W - 10) left = p.x - tw - 16;
    var top = Math.min(Math.max(8, p.y - 30), this.H - th - 8);
    this.tip.style.left = left + 'px';
    this.tip.style.top = top + 'px';
  };

  global.KLineChart = KLineChart;
  global.KLFmt = { price: fmtPrice, vol: fmtVol };
})(window);
