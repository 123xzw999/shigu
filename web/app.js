/* ==========================================================================
   交易很轻松 · 前端主逻辑
   ========================================================================== */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var fmt = window.KLFmt;

  var state = {
    code: null,
    scale: 240,
    canBack: false,
    data: null,
    lastRound: -1,
    status: null,
    timer: null,
    chart: null,
    searchTimer: null,
    suggestIdx: -1,
    suggestList: [],
  };

  // ------------------------------------------------------------ 工具
  function api(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) { return r.json(); });
  }

  function el(tag, cls, html) {
    var d = document.createElement(tag);
    if (cls) d.className = cls;
    if (html != null) d.innerHTML = html;
    return d;
  }

  function colorOf(v) { return v > 0 ? 'up' : (v < 0 ? 'down' : 'flat'); }
  function sign(v, digits) {
    if (v == null || isNaN(v)) return '—';
    var d = digits == null ? 2 : digits;
    return (v > 0 ? '+' : '') + v.toFixed(d);
  }
  function fmtAmount(v) {
    if (!v) return '—';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
    if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
    return v.toFixed(0);
  }

  // ------------------------------------------------------------ 图表
  function initChart() {
    var cv = $('kline');
    state.chart = new window.KLineChart(cv, $('tip'));
    window.addEventListener('resize', function () {
      clearTimeout(state.timer);
      state.timer = setTimeout(function () { state.chart.draw(); }, 120);
    });
    var ro = new ResizeObserver(function () { state.chart.draw(); });
    ro.observe($('canvasWrap'));
  }

  // ------------------------------------------------------------ 加载
  function load(code, scale, silent) {
    if (code) state.code = code;
    if (scale) state.scale = scale;
    if (!state.code) return;
    if (!silent) $('loading').classList.remove('hide');
    api('/api/snapshot?code=' + encodeURIComponent(state.code) + '&scale=' + state.scale)
      .then(function (d) {
        $('loading').classList.add('hide');
        if (!d || !d.ok) {
          renderError(d && d.reason ? d.reason : '数据获取失败');
          return;
        }
        applyData(d);
      })
      .catch(function (e) {
        $('loading').classList.add('hide');
        // 网络抖动：不立刻报错，交给重连机制
        if (!state.data) renderError('连接中断，正在重试…');
        state.retry = (state.retry || 0) + 1;
      });
  }

  // 区分「整份分析更新」和「只是行情跳动」，避免 5 秒一次把整个 DOM 重建
  function applyData(d) {
    var prev = state.data;
    // 后端返回的是规范化代码（sz002185），用它修正地址栏，别让 URL 里出现裸代码
    if (d.symbol && d.symbol !== state.code) {
      state.code = d.symbol;
      syncHash(false);
    }
    var light = false;
    if (prev && prev.ok && d.ok && prev.symbol === d.symbol &&
        prev.analysis_scale === d.analysis_scale &&
        prev.analysis && d.analysis && prev.view && d.view &&
        prev.analysis.score && d.analysis.score &&
        prev.analysis.score.score === d.analysis.score.score &&
        (prev.view.bars || []).length === (d.view.bars || []).length) {
      light = true;
    }
    state.data = d;
    if (light) {
      renderQuote(d);
      state.chart.setData({
        bars: d.view.bars, ind: d.view.ind, chan: d.view.chan,
        chip: d.analysis.chip, navMode: d.view.nav_mode || false,
      });
      state.chart.draw();
      return;
    }
    renderAll(d);
  }

  function renderError(msg) {
    $('stockname').textContent = '—';
    $('stockcode').textContent = '';
    $('price').textContent = '—';
    $('chg').textContent = '';
    $('pct').textContent = '';
    $('meta').innerHTML = '<span style="color:#e01b1b">' + msg + '</span>';
    $('loading').textContent = msg;
    $('loading').classList.remove('hide');
  }

  // ------------------------------------------------------------ 渲染
  function renderAll(d) {
    var panel = $('panel');
    var st = panel ? panel.scrollTop : 0;
    // 周期按钮与实际分析周期对齐（数据不足时后端会回退到日线）
    var realScale = d.analysis_scale || state.scale;
    document.querySelectorAll('#scaleTabs button').forEach(function (b) {
      b.classList.toggle('on', parseInt(b.dataset.scale, 10) === realScale);
    });
    var ss = $('scoreScale');
    if (ss) {
      ss.textContent = d.analysis_scale_name || '日线';
      ss.className = 'tag' + (realScale !== 240 ? ' up' : '');
    }
    renderQuote(d);
    renderChart(d);
    renderScore(d.analysis.score);
    renderFund(d);
    renderAdvice(d.analysis);
    renderChip(d.analysis.chip);
    renderChan(d.analysis.chan);
    renderTurning(d.analysis.turning);
    renderPhase(d.analysis.phase, d.analysis.segments);
    renderPatterns(d.analysis.patterns);
    renderPerf(d.analysis.summary);
    if (panel) panel.scrollTop = st;
    renderWatch();
  }

  function renderQuote(d) {
    var q = d.quote || {};
    var a = d.analysis || {};
    $('stockname').textContent = d.name || q.name || '—';
    $('stockcode').textContent = (d.symbol || '').toUpperCase();
    var kindMap = { stock: '股票', fund: '基金/ETF', ofund: '场外基金', index: '指数', global: '外围' };
    var kb = $('stockkind');
    var ktxt = kindMap[d.kind] || '证券';
    if (d.kind === 'global') {
      ktxt = ({ US: '美股', HK: '港股', FX: '外汇', CM: '商品', CN: '国内期货', GL: '全球指数' })[d.market] || '外围市场';
    } else if (d.market && d.market !== ktxt && d.kind !== 'ofund') {
      ktxt += ' · ' + d.market;
    }
    kb.textContent = ktxt;
    kb.className = 'badge' + (a.phase && a.phase.phase === '拉升' ? ' hot' : '');

    var price = q.price || 0;
    var chg = q.change || 0;
    var pct = q.change_pct || 0;
    var cls = colorOf(chg);
    $('price').textContent = fmt.price(price);
    $('price').className = 'price ' + cls;
    $('chg').textContent = sign(chg, price < 10 ? 3 : 2);
    $('chg').className = 'chg ' + cls;
    $('pct').textContent = sign(pct, 2) + '%';
    $('pct').className = 'pct ' + cls;

    var turnover = a.summary && a.summary.turnover;
    var meta;
    if (d.kind === 'global') {
      var pos52 = q.pos52;
      meta = [
        ['今开', fmt.price(q.open), colorOf(q.open - q.prev_close)],
        ['昨收', fmt.price(q.prev_close), ''],
        ['最高', fmt.price(q.high), ''],
        ['最低', fmt.price(q.low), ''],
      ];
      if (pos52 != null) meta.push(['52周分位', pos52.toFixed(1) + '%', '']);
      if (a.summary && a.summary.position) meta.push(['区间位置', a.summary.position.replace('52周分位 ', ''), '']);
    } else {
      meta = [
        ['今开', fmt.price(q.open), colorOf(q.open - q.prev_close)],
        ['昨收', fmt.price(q.prev_close), ''],
        ['最高', fmt.price(q.high), colorOf(q.high - q.prev_close)],
        ['最低', fmt.price(q.low), colorOf(q.low - q.prev_close)],
        ['成交量', fmtAmount(q.volume), ''],
        ['成交额', fmtAmount(q.amount), ''],
      ];
      if (turnover) meta.push(['换手率', turnover.toFixed(2) + '%', '']);
      if (a.summary && a.summary.float_shares) meta.push(['流通股', fmtAmount(a.summary.float_shares), '']);
    }
    var html = meta.map(function (m) {
      return '<span>' + m[0] + '<b class="' + m[2] + '">' + (m[1] || '—') + '</b></span>';
    }).join('');
    if (q.date) html += '<span>更新<b>' + q.date + ' ' + (q.time || '') + '</b></span>';
    $('meta').innerHTML = html;

    var sc = a.score;
    if (sc) {
      $('scoreMini').textContent = (sc.score > 0 ? '+' : '') + sc.score;
      $('scoreMini').style.color = sc.level.color;
      $('levelMini').textContent = sc.level.name;
      $('levelMini').style.color = sc.level.color;
    }
  }

  function renderChart(d) {
    var v = d.view || {};
    state.chart.setData({
      bars: v.bars || [],
      ind: v.ind || {},
      chan: v.chan,
      turning: v.turning,
      chip: d.analysis ? d.analysis.chip : null,
      navMode: v.nav_mode || false,
    });
    state.chart.draw();
  }

  // ------------------------------------------------------------ 评分
  function renderScore(sc) {
    if (!sc) return;
    $('gNum').textContent = (sc.score > 0 ? '+' : '') + sc.score;
    $('gNum').style.color = sc.level.color;
    $('gLv').textContent = sc.level.name;
    $('gLv').style.color = sc.level.color;
    $('gConf').textContent = sc.confidence + '%';
    $('gAgree').textContent = sc.agreement + '%';
    drawGauge(sc.score, sc.level.color);

    var box = $('dims');
    box.innerHTML = '';
    (sc.dimensions || []).forEach(function (dm) {
      var v = dm.score100;
      var row = el('div', 'dim');
      row.appendChild(el('div', 'dn', dm.name));
      var bar = el('div', 'dbar');
      bar.appendChild(el('div', 'mid'));
      var fill = el('div', 'fill');
      var w = Math.min(50, Math.abs(v) / 2);
      fill.style.width = w + '%';
      if (v >= 0) { fill.style.left = '50%'; fill.style.background = '#ef232a'; }
      else { fill.style.left = (50 - w) + '%'; fill.style.background = '#14b143'; }
      if (dm.side === 'na') { fill.style.width = '0%'; }
      bar.appendChild(fill);
      row.appendChild(bar);
      var dv = el('div', 'dv', dm.side === 'na' ? '—' : sign(v, 0));
      dv.style.color = dm.side === 'na' ? '#b4bac1' : (v >= 0 ? '#ef232a' : '#14b143');
      row.appendChild(dv);
      row.appendChild(el('div', 'dt', dm.tag));
      row.title = (dm.evidence || []).join('\n');
      box.appendChild(row);
    });
  }

  function drawGauge(score, color) {
    var cv = $('gauge');
    var dpr = window.devicePixelRatio || 1;
    var w = 220, h = 130;
    cv.width = w * dpr; cv.height = h * dpr;
    cv.style.width = w + 'px'; cv.style.height = h + 'px';
    var ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var cx = w / 2, cy = h - 16, r = 78;
    var a0 = Math.PI, a1 = Math.PI * 2;

    // 背景轨道
    ctx.beginPath();
    ctx.arc(cx, cy, r, a0, a1);
    ctx.strokeStyle = '#eef1f4';
    ctx.lineWidth = 14;
    ctx.lineCap = 'round';
    ctx.stroke();

    // 刻度分段（绿-灰-红）
    var segs = [
      [0, 0.3, '#14b143'], [0.3, 0.42, '#7fc9a0'],
      [0.42, 0.58, '#dfe4e9'],
      [0.58, 0.7, '#f4a3a3'], [0.7, 1, '#ef232a']
    ];
    segs.forEach(function (s) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, a0 + (a1 - a0) * s[0] + 0.012, a0 + (a1 - a0) * s[1] - 0.012);
      ctx.strokeStyle = s[2];
      ctx.globalAlpha = 0.28;
      ctx.lineWidth = 14;
      ctx.stroke();
      ctx.globalAlpha = 1;
    });

    // 进度弧
    var t = (Math.max(-100, Math.min(100, score)) + 100) / 200;
    var ae = a0 + (a1 - a0) * t;
    ctx.beginPath();
    ctx.arc(cx, cy, r, a0, ae);
    ctx.strokeStyle = color;
    ctx.lineWidth = 14;
    ctx.lineCap = 'round';
    ctx.stroke();

    // 指针
    var px = cx + Math.cos(ae) * (r - 20);
    var py = cy + Math.sin(ae) * (r - 20);
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(ae) * (r - 34), cy + Math.sin(ae) * (r - 34));
    ctx.lineTo(px, py);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    // 端点标签
    ctx.font = '10px -apple-system,"PingFang SC",Arial';
    ctx.fillStyle = '#b4bac1';
    ctx.textAlign = 'center';
    ctx.fillText('-100', cx - r, cy + 14);
    ctx.fillText('0', cx, cy - r - 6);
    ctx.fillText('+100', cx + r, cy + 14);
  }

  // ------------------------------------------------------------ 基金评价
  function renderFund(d) {
    var card = $('fundCard');
    var f = d.analysis && d.analysis.fund;
    if (!f || !f.meta) {
      card.style.display = 'none';
      return;
    }
    card.style.display = '';
    var meta = f.meta, m = f.metrics || {}, sc = f.score, sty = f.style;

    $('fundType').textContent = meta.type_name || '—';
    $('fundType').className = 'tag ' + (meta.passive ? '' : 'up');

    if (sc) {
      $('fundScore').textContent = (sc.score > 0 ? '+' : '') + sc.score;
      $('fundScore').style.color = sc.level.color;
    } else {
      $('fundScore').textContent = '—';
    }
    $('fundClass').innerHTML = '<b>' + (meta.type_name || '—') + '</b>' +
      (meta.passive ? ' · 被动跟踪' : (meta.semi_active ? ' · 半主动' : ' · 主动管理'));
    $('fundBench').innerHTML = '基准 <b>' + (meta.bench_name || '—') + '</b>' +
      (meta.track_index ? ' · 跟踪 ' + meta.track_index : '');

    var kpi = $('fundKpi');
    kpi.innerHTML = '';
    if (!m || m.days == null) {
      kpi.innerHTML = '<div class="fk" style="grid-column:1/-1"><span>绩效数据不足（需至少 30 个交易日）</span></div>';
    } else {
      var rows = [
        ['区间收益', sign(m.total_ret, 2) + '%', m.total_ret],
        ['年化收益', sign(m.ann_ret, 2) + '%', m.ann_ret],
        ['最大回撤', '-' + m.mdd.toFixed(2) + '%', -1],
        ['年化波动', m.ann_vol.toFixed(2) + '%', null],
        ['夏普比率', m.sharpe.toFixed(2), m.sharpe],
        ['卡玛比率', m.calmar.toFixed(2), m.calmar],
      ];
      if (m.tracking_error != null) rows.push(['跟踪误差', m.tracking_error.toFixed(2) + '%', null]);
      if (m.excess_ann != null) rows.push(['年化超额', sign(m.excess_ann, 2) + '%', m.excess_ann]);
      if (m.beta != null) rows.push(['Beta', m.beta.toFixed(2), null]);
      if (m.corr != null) rows.push(['与基准相关', m.corr.toFixed(3), null]);
      if (m.alpha != null) rows.push(['Jensen α', sign(m.alpha, 2) + '%', m.alpha]);
      if (m.info_ratio != null) rows.push(['信息比率', m.info_ratio.toFixed(2), m.info_ratio]);
      if (m.win_rate != null) rows.push(['上涨占比', m.win_rate.toFixed(1) + '%', null]);
      rows.forEach(function (r) {
        var el2 = document.createElement('div');
        el2.className = 'fk';
        var a = document.createElement('span');
        a.textContent = r[0];
        var b = document.createElement('b');
        b.textContent = r[1];
        if (r[2] != null) b.style.color = r[2] > 0 ? '#ef232a' : (r[2] < 0 ? '#14b143' : '#555');
        el2.appendChild(a); el2.appendChild(b);
        kpi.appendChild(el2);
      });
    }

    var styleBox = $('fundStyle');
    if (sty && sty.text) {
      styleBox.style.display = '';
      styleBox.textContent = sty.text;
      styleBox.className = 'fund-style ' + (sty.level === 'passive' ? 'passive' :
        (sty.level === 'active' ? 'active' : ''));
    } else {
      styleBox.style.display = 'none';
    }

    var box = $('fundDims');
    box.innerHTML = '';
    if (!sc) return;
    (sc.dimensions || []).forEach(function (dm) {
      var v = dm.score100;
      var row = document.createElement('div');
      row.className = 'dim';
      row.appendChild(el('div', 'dn', dm.name));
      var bar = el('div', 'dbar');
      bar.appendChild(el('div', 'mid'));
      var fill = el('div', 'fill');
      var w = Math.min(50, Math.abs(v) / 2);
      fill.style.width = w + '%';
      if (v >= 0) { fill.style.left = '50%'; fill.style.background = '#ef232a'; }
      else { fill.style.left = (50 - w) + '%'; fill.style.background = '#14b143'; }
      bar.appendChild(fill);
      row.appendChild(bar);
      var dv = el('div', 'dv', sign(v, 0));
      dv.style.color = v >= 0 ? '#ef232a' : '#14b143';
      row.appendChild(dv);
      row.appendChild(el('div', 'dt', dm.tag));
      row.title = (dm.evidence || []).join('\n');
      box.appendChild(row);
    });
  }

  // ------------------------------------------------------------ 外围市场
  var GB_SHOW = ['gb_$dji', 'gb_$ixic', 'rt_hkHSI', 'int_nikkei',
    'hf_GC', 'hf_CL', 'fx_susdcny'];

  function loadGlobal() {
    api('/api/global').then(function (d) {
      if (!d || !d.ok) return;
      state.global = d;
      renderGlobalBar(d);
      if ($('gmodal').classList.contains('show')) renderGlobalModal(d);
    }).catch(function () { /* 静默 */ });
  }

  function renderGlobalBar(d) {
    var box = $('globalbar');
    var idx = {};
    (d.groups || []).forEach(function (g) {
      g.items.forEach(function (it) { idx[it.symbol] = it; });
    });
    box.innerHTML = '';
    GB_SHOW.forEach(function (k) {
      var it = idx[k];
      if (!it) return;
      var div = document.createElement('div');
      div.className = 'gb-item';
      var cls = it.change_pct > 0 ? 'up' : (it.change_pct < 0 ? 'down' : 'flat');
      div.innerHTML = '<span class="gn">' + it.name + '</span>' +
        '<span class="gp ' + cls + '">' + fmt.price(it.price) + '</span>' +
        '<span class="gc ' + cls + '">' + sign(it.change_pct, 2) + '%</span>';
      div.onclick = function () { load(it.symbol, 240); };
      box.appendChild(div);
    });

    var r = d.risk || {};
    if (r.score != null) {
      $('graiVal').textContent = (r.score > 0 ? '+' : '') + r.score;
      $('graiVal').style.color = r.level.color;
      $('graiLv').textContent = r.level.name;
      $('graiLv').style.color = r.level.color;
    }
  }

  function renderGlobalModal(d) {
    $('gmodalTime').textContent = d.updated || '';
    var r = d.risk || {};
    var html = '';

    // GRAI
    if (r.score != null) {
      html += '<div class="grai-box">';
      html += '<div class="grai-left">';
      html += '<div class="grai-score" style="color:' + r.level.color + '">' +
        (r.score > 0 ? '+' : '') + r.score + '</div>';
      html += '<div class="grai-lv" style="color:' + r.level.color + '">' + r.level.name + '</div>';
      html += '<div class="grai-hint">' + (r.a_share || '') + '</div>';
      html += '</div><div class="grai-right">';
      var mxC = 0;
      (r.components || []).forEach(function (c) {
        if (Math.abs(c.contrib) > mxC) mxC = Math.abs(c.contrib);
      });
      mxC = mxC || 1;
      (r.components || []).forEach(function (c) {
        var v = c.contrib;
        var w = Math.min(46, Math.abs(v) / mxC * 46);
        var isPos = c.key === 'pos';
        // 条形方向跟随「涨跌」，宽度跟随「贡献大小」—— 否则黄金涨、权重为负时方向会反直觉
        var up = isPos ? v >= 0 : c.pct >= 0;
        html += '<div class="grai-comp"><span class="cn">' + c.name + '</span>';
        html += '<span class="cbar"><i class="mid"></i><i class="f" style="' +
          (up ? 'left:50%;background:#ef232a;' : 'left:' + (50 - w) + '%;background:#14b143;') +
          'width:' + w + '%"></i></span>';
        html += '<span class="cv ' + (c.pct > 0 ? 'up' : (c.pct < 0 ? 'down' : '')) + '">' +
          (isPos ? c.pct.toFixed(1) + '分位' : sign(c.pct, 2) + '%') + '</span>';
        html += '<span class="cw" title="权重 ' + c.weight + '，贡献 ' + v.toFixed(4) + '">w' +
          c.weight.toFixed(2) + '</span></div>';
      });
      if ((r.signals || []).length) {
        html += '<div class="grai-sig">';
        r.signals.forEach(function (s) {
          html += '<div class="sg ' + s.level + '">' + s.text + '</div>';
        });
        html += '</div>';
      }
      html += '</div></div>';
    }

    // 分组
    (d.groups || []).forEach(function (g) {
      html += '<div class="gm-group"><h4>' + g.name + '</h4><div class="gm-grid">';
      g.items.forEach(function (it) {
        var cls = it.change_pct > 0 ? 'up' : (it.change_pct < 0 ? 'down' : 'flat');
        html += '<div class="gm-cell" data-sym="' + it.symbol + '">' +
          '<span class="n">' + it.name + '</span>' +
          '<span class="v ' + cls + '">' + fmt.price(it.price) + '</span>' +
          '<span class="p ' + cls + '">' + sign(it.change_pct, 2) + '%</span></div>';
      });
      html += '</div></div>';
    });

    var box = $('gmodalContent');
    box.innerHTML = html;
    box.querySelectorAll('.gm-cell').forEach(function (c) {
      c.onclick = function () {
        closeGlobal();
        load(c.dataset.sym, 240);
      };
    });
  }

  function openGlobal() {
    $('gmodal').classList.add('show');
    if (state.global) renderGlobalModal(state.global);
    else loadGlobal();
  }

  function closeGlobal() {
    $('gmodal').classList.remove('show');
  }

  // ------------------------------------------------------------ 路由
  //
  //   #sh600519                  个股
  //   #list/sector               板块列表（全部）
  //   #list/sector/半导体         板块列表（筛选某个主题）
  //
  // 用户主动切换 → pushState（产生历史，返回键可回退）
  // 5 秒轮询刷新 → replaceState（不污染历史）

  var rawLoad = null;      // 未包装的 load，供路由恢复时调用

  function routeHash() {
    if (state.listKey === 'board') {
      return '#list/board/' + encodeURIComponent(state.boardCode || '');
    }
    if (state.listKey) {
      var h = '#list/' + state.listKey;
      if (state.listTheme) h += '/' + encodeURIComponent(state.listTheme);
      return h;
    }
    return '#' + (state.code || 'sh600519');
  }

  function syncHash(push) {
    var h = routeHash();
    if (location.hash === h) return;
    if (push) {
      var depth = ((history.state && history.state.d) || 0) + 1;
      history.pushState({ r: h, d: depth }, '', h);
      state.canBack = depth > 0;
      updateBackBtn();
    } else {
      var d0 = (history.state && history.state.d) || 0;
      history.replaceState({ r: h, d: d0 }, '', h);
    }
  }

  function applyRoute() {
    state.canBack = ((history.state && history.state.d) || 0) > 0;
    updateBackBtn();
    var h = (location.hash || '').replace(/^#/, '');
    try { h = decodeURIComponent(h); } catch (e) { /* ignore */ }
    if (!h) return;
    if (h.indexOf('list/') === 0) {
      var p = h.split('/');
      if (p[1] === 'board') openBoard(p[2] || '', '', false);
      else openList(p[1], p[2] || '', false);
    } else {
      if (state.listKey) closeList(false);
      if (rawLoad) rawLoad(h, state.scale, false);
    }
  }

  function updateBackBtn() {
    var b = $('btnBack');
    if (b) b.disabled = !state.canBack;
  }

  function goBack() {
    if (!state.canBack) return;
    history.back();
  }

  // ------------------------------------------------------------ 列表视图
  var LIST_NAV = {
    stock: {
      type: 'stock',
      sorts: [['changepercent', '涨跌幅'], ['turnoverratio', '换手率'], ['amount', '成交额']],
    },
    fund: {
      type: 'etf',
      tabs: [['etf', '场内ETF'], ['lof', '场内LOF'], ['ofund', '场外基金']],
    },
    sector: { type: 'sector' },
    rank: {
      type: 'stock',
      sorts: [['changepercent', '涨跌幅'], ['turnoverratio', '换手率'],
        ['amount', '成交额'], ['volume', '成交量']],
    },
  };

  function openList(key, theme, push) {
    var cfg = LIST_NAV[key];
    if (!cfg) return;
    state.listKey = key;
    state.listType = cfg.type;
    state.listSort = cfg.sorts ? cfg.sorts[0][0] : 'changepercent';
    state.listTheme = theme || '';
    state.boardCode = null;
    hideThemeTabs();

    var tabs = $('lvTypeTabs');
    tabs.innerHTML = '';
    tabs.style.display = cfg.tabs ? '' : 'none';
    if (cfg.tabs) {
      cfg.tabs.forEach(function (t) {
        var b = document.createElement('button');
        b.textContent = t[1];
        b.className = t[0] === state.listType ? 'on' : '';
        b.onclick = function () {
          state.listType = t[0];
          Array.prototype.forEach.call(tabs.children, function (x) { x.classList.remove('on'); });
          b.classList.add('on');
          $('lvTitle').textContent = t[1];
          loadList();
        };
        tabs.appendChild(b);
      });
    }

    var sorts = $('lvSorts');
    sorts.innerHTML = '';
    sorts.style.display = cfg.sorts ? '' : 'none';
    if (cfg.sorts) {
      cfg.sorts.forEach(function (s) {
        var b = document.createElement('button');
        b.textContent = s[1];
        b.className = s[0] === state.listSort ? 'on' : '';
        b.onclick = function () {
          state.listSort = s[0];
          Array.prototype.forEach.call(sorts.children, function (x) { x.classList.remove('on'); });
          b.classList.add('on');
          loadList();
        };
        sorts.appendChild(b);
      });
    }

    $('lvTitle').textContent = { stock: '个股', fund: '基金', sector: '板块', rank: '排行' }[key] || key;
    $('listview').classList.add('show');
    syncHash(push !== false);
    loadList();
  }

  function closeList(push) {
    $('listview').classList.remove('show');
    hideThemeTabs();
    state.listKey = null;
    state.boardCode = null;
    if (push) syncHash(true);
  }

  // ------------------------------------------------------------ 板块成分股
  //
  // 点板块不再直接跳到领涨股，而是先列出该板块的全部成分股，
  // 再点某一只才进个股分析。
  function openBoard(code, name, push) {
    if (!code) return;
    state.listKey = 'board';
    state.boardCode = code;
    state.boardName = name || '';
    state.listType = 'board';
    hideThemeTabs();
    $('lvTypeTabs').style.display = 'none';
    $('lvSorts').style.display = 'none';
    $('lvTitle').textContent = name || '板块成分股';
    $('lvSub').textContent = '';
    $('listview').classList.add('show');
    syncHash(push !== false);
    loadBoard();
  }

  function loadBoard() {
    var box = $('lvTable');
    box.innerHTML = '<div class="lv-empty">加载中…</div>';
    api('/api/board?code=' + encodeURIComponent(state.boardCode))
      .then(function (d) {
        if (!d || !d.ok) {
          box.innerHTML = '<div class="lv-empty">' + ((d && d.reason) || '板块数据加载失败') + '</div>';
          return;
        }
        state.boardName = d.name;
        $('lvTitle').textContent = d.name;
        renderList({
          ok: true, type: 'board',
          subtitle: d.total + ' 只成分股 · 涨 ' + d.up + ' 跌 ' + d.down +
            ' · 均 ' + sign(d.avg_pct, 2) + '%' + (d.theme ? ' · ' + d.theme : ''),
          items: d.items,
        });
      })
      .catch(function (e) {
        box.innerHTML = '<div class="lv-empty">网络异常：' + e + '</div>';
      });
  }

  function loadList() {
    var box = $('lvTable');
    box.innerHTML = '<div class="lv-empty">加载中…</div>';
    var q = '/api/list?type=' + state.listType + '&sort=' + state.listSort + '&num=120';
    if (state.listType === 'sector' && state.listTheme) {
      q += '&theme=' + encodeURIComponent(state.listTheme);
    }
    api(q)
      .then(function (d) {
        if (!d || !d.ok) {
          box.innerHTML = '<div class="lv-empty">加载失败：' + ((d && d.reason) || '未知错误') + '</div>';
          return;
        }
        renderList(d);
      })
      .catch(function (e) {
        box.innerHTML = '<div class="lv-empty">网络异常：' + e + '</div>';
      });
  }

  // 板块的主题筛选标签（半导体 / AI算力 / 医药医疗 …）
  function renderThemeTabs(themes) {
    var box = $('lvTabs');
    box.innerHTML = '';
    box.style.display = '';

    var all = document.createElement('button');
    all.textContent = '全部';
    all.className = state.listTheme ? '' : 'on';
    all.onclick = function () {
      state.listTheme = '';
      loadList();
      syncHash(true);
    };
    box.appendChild(all);

    (themes || []).forEach(function (t) {
      var b = document.createElement('button');
      var cls = t.change_pct > 0 ? 'up' : (t.change_pct < 0 ? 'down' : '');
      b.innerHTML = t.name + '<span class="' + cls + '" style="margin-left:4px">' +
        (t.change_pct > 0 ? '+' : '') + t.change_pct + '%</span>';
      b.className = state.listTheme === t.name ? 'on' : '';
      b.onclick = function () {
        state.listTheme = (state.listTheme === t.name) ? '' : t.name;
        loadList();
        syncHash(true);
      };
      box.appendChild(b);
    });
  }

  function hideThemeTabs() {
    var box = $('lvTabs');
    box.innerHTML = '';
    box.style.display = 'none';
  }

  function renderList(d) {
    $('lvSub').textContent = d.subtitle || '';
    if (state.listKey === 'fund' && state.listType === 'ofund') {
      $('lvTitle').textContent = '场外基金';
    }
    if (d.themes && state.listType === 'sector') renderThemeTabs(d.themes);

    var isSector = state.listType === 'sector';
    var rows = ['<div class="lv-row head">' +
      '<span>名称</span><span>' + (isSector ? '主题' : '代码') + '</span>' +
      '<span style="text-align:right">' + (isSector ? '成交额' : '最新') + '</span>' +
      '<span style="text-align:right">涨跌幅</span><span>备注</span></div>'];
    (d.items || []).forEach(function (it) {
      var cls = it.change_pct > 0 ? 'up' : (it.change_pct < 0 ? 'down' : 'flat');
      var mid = isSector ? (it.theme || '—') : (it.symbol || '').toUpperCase();
      var third = isSector
        ? (it.amount_yi ? it.amount_yi + '亿' : '—')
        : fmt.price(it.price);
      rows.push('<div class="lv-row" data-sym="' + it.symbol + '"' +
        ' data-code="' + (it.code || '') + '" data-name="' + (it.name || '') + '">' +
        '<span class="lv-name">' + it.name + '</span>' +
        '<span class="lv-code">' + mid + '</span>' +
        '<span class="lv-price ' + (isSector ? '' : cls) + '">' + third + '</span>' +
        '<span class="lv-pct ' + cls + '">' + sign(it.change_pct, 2) + '%</span>' +
        '<span class="lv-extra">' + (it.extra || '') + '</span></div>');
    });
    if (!(d.items || []).length) {
      rows.push('<div class="lv-empty">暂无数据</div>');
    }
    var box = $('lvTable');
    box.innerHTML = rows.join('');
    box.querySelectorAll('.lv-row[data-sym]').forEach(function (r) {
      r.onclick = function () {
        // 板块行 → 先看成分股；成分股行 → 进个股分析
        if (state.listType === 'sector') {
          openBoard(r.dataset.code, r.dataset.name, true);
          return;
        }
        var sym = r.dataset.sym;
        if (!sym) return;
        closeList();
        load(sym, 240, false, true);
        api('/api/watch?action=add&code=' + encodeURIComponent(sym)).then(renderWatch);
      };
    });
    box.scrollTop = 0;
  }

  // ------------------------------------------------------------ 全屏
  function toggleFullscreen(force) {
    var card = document.querySelector('.chartcard');
    if (!card) return;
    var btn = $('btnFullscreen');
    var want = (typeof force === 'boolean')
      ? force
      : !card.classList.contains('fullscreen');
    card.classList.toggle('fullscreen', want);
    btn.classList.toggle('on', want);
    btn.innerHTML = want ? '⛶ 退出全屏' : '⛶ 全屏';
    // 全屏后宽度变化，给浏览器一帧时间完成布局再重绘
    setTimeout(function () {
      if (!state.chart || !state.chart.bars.length) return;
      state.chart.count = Math.min(want ? 200 : 120, state.chart.bars.length);
      state.chart.end = state.chart.bars.length;
      state.chart.draw();
    }, 80);
  }

  // ------------------------------------------------------------ 建议
  function renderAdvice(a) {
    var ad = a.advice || {};
    var lv = a.levels || {};
    $('actTag').textContent = ad.action || '—';
    $('actTag').className = 'tag ' + (a.score && a.score.score > 0 ? 'up' : 'down');
    $('adviceMain').textContent = ad.advice || '—';
    var ul = $('adviceNotes');
    ul.innerHTML = '';
    (ad.notes || []).forEach(function (n) {
      ul.appendChild(el('li', '', n));
    });

    var box = $('levels');
    box.innerHTML = '';
    var sup = (lv.supports && lv.supports[0]) || null;
    var res = (lv.resists && lv.resists[0]) || null;
    // 外围市场 / 场外基金没有关键价位，整块隐藏，避免一片「—」
    if (!sup && !res) {
      box.style.display = 'none';
      return;
    }
    box.style.display = '';
    var items = [
      ['支撑', sup ? fmt.price(sup.price) : '—', sup ? (sup.label || '') + ' ' + sign(sup.dist_pct, 1) + '%' : '', '#14b143'],
      ['压力', res ? fmt.price(res.price) : '—', res ? (res.label || '') + ' ' + sign(res.dist_pct, 1) + '%' : '', '#ef232a'],
      ['盈亏比', lv.risk_reward != null ? lv.risk_reward.toFixed(2) : '—', '止损 ' + fmt.price(lv.stop), '#555'],
    ];
    items.forEach(function (it) {
      var d = el('div', 'lv-item');
      d.appendChild(el('div', 'k', it[0]));
      var v = el('div', 'v', it[1]);
      v.style.color = it[3];
      d.appendChild(v);
      d.appendChild(el('div', 'd', it[2] || ''));
      box.appendChild(d);
    });
  }

  // ------------------------------------------------------------ 筹码
  function renderChip(cp) {
    var cv = $('chip');
    var ctx = cv.getContext('2d');
    var okChip = !!(cp && cp.ok);
    var wrap = document.querySelector('.chip-wrap');
    wrap.style.height = okChip ? '230px' : '68px';

    var dpr = window.devicePixelRatio || 1;
    var rect = cv.getBoundingClientRect();
    var w = rect.width || 340, h = rect.height || (okChip ? 230 : 68);
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var stats = $('chipStats');
    var zones = $('zones');
    stats.innerHTML = '';
    zones.innerHTML = '';

    if (!okChip) {
      $('chipTag').textContent = '不适用';
      ctx.fillStyle = '#b4bac1';
      ctx.font = '12px -apple-system,"PingFang SC",Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      var isG = state.data && state.data.kind === 'global';
      ctx.fillText(isG ? '外围市场无流通股本，不做筹码分布' : '该标的无筹码数据（指数 / 场外基金）',
        w / 2, h / 2);
      return;
    }
    $('chipTag').textContent = 'CYQ · ' + cp.days_used + '日';

    var dist = cp.distribution || [];
    if (!dist.length) return;
    var padL = 4, padR = 48, padT = 14, padB = 14;
    var plotW = w - padL - padR, plotH = h - padT - padB;
    var lo = cp.range[0], hi = cp.range[1];
    var yOf = function (p) { return padT + (hi - p) / (hi - lo) * plotH; };

    var mxAll = 0;
    dist.forEach(function (d) { if (d.m > mxAll) mxAll = d.m; if (d.r > mxAll) mxAll = d.r; });
    if (mxAll <= 0) mxAll = 1;
    // 背靠背布局：中间为基准线，主力向右、散户向左
    var midX = padL + plotW * 0.44;
    var half = Math.min(plotW * 0.50, plotW * 0.50);
    var scale = half / mxAll;

    // 主力区 / 散户区 背景
    function band(z, fill) {
      if (!z) return;
      var y1 = yOf(z.high), y2 = yOf(z.low);
      ctx.fillStyle = fill;
      ctx.fillRect(padL, Math.min(y1, y2), plotW, Math.abs(y2 - y1));
    }
    band(cp.main_zone, 'rgba(255,143,31,.10)');
    band(cp.retail_zone, 'rgba(59,130,246,.07)');

    // 条形
    var bh = Math.max(1.2, plotH / dist.length * 1.1);
    dist.forEach(function (d) {
      var y = yOf(d.p);
      ctx.fillStyle = 'rgba(255,143,31,.88)';
      ctx.fillRect(midX, y - bh / 2, Math.max(0.4, d.m * scale), bh);
      ctx.fillStyle = 'rgba(59,130,246,.62)';
      ctx.fillRect(midX - Math.max(0.4, d.r * scale), y - bh / 2, Math.max(0.4, d.r * scale), bh);
    });

    // 基准线
    ctx.strokeStyle = '#dfe4e9';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(midX + 0.5, padT);
    ctx.lineTo(midX + 0.5, padT + plotH);
    ctx.stroke();

    // 方向标注
    ctx.font = '9.5px -apple-system,"PingFang SC",Arial';
    ctx.textAlign = 'right';
    ctx.fillStyle = 'rgba(59,130,246,.85)';
    ctx.fillText('← 散户', midX - 4, padT - 4);
    ctx.textAlign = 'left';
    ctx.fillStyle = 'rgba(255,143,31,.9)';
    ctx.fillText('主力 →', midX + 4, padT - 4);

    // 现价线
    var yp = yOf(cp.price);
    ctx.strokeStyle = '#ef232a';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(padL, yp);
    ctx.lineTo(padL + plotW, yp);
    ctx.stroke();
    ctx.setLineDash([]);

    // 主力成本 / 散户成本
    [[cp.main_cost, '#ff8f1f'], [cp.retail_cost, '#3b82f6']].forEach(function (p) {
      var y = yOf(p[0]);
      ctx.strokeStyle = p[1];
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(midX - 14, y);
      ctx.lineTo(midX + 14, y);
      ctx.stroke();
    });

    // 右侧价格刻度
    ctx.font = '10px -apple-system,"PingFang SC",Arial';
    ctx.fillStyle = '#8d949c';
    ctx.textAlign = 'left';
    var ticks = 5;
    for (var i = 0; i <= ticks; i++) {
      var p = hi - (hi - lo) * i / ticks;
      var y = padT + plotH * i / ticks;
      ctx.fillText(fmt.price(p), padL + plotW + 5, y + 3);
    }
    // 现价标签
    ctx.fillStyle = '#ef232a';
    ctx.fillText(fmt.price(cp.price), padL + plotW + 5, yp + 3);

    // 统计
    var rows = [
      ['主力成本', fmt.price(cp.main_cost)],
      ['散户成本', fmt.price(cp.retail_cost)],
      ['控盘度', cp.control.toFixed(1) + '%'],
      ['集中度', (cp.concentration * 100).toFixed(1)],
      ['获利盘', cp.profit_ratio.toFixed(1) + '%'],
      ['套牢盘', cp.trapped_ratio.toFixed(1) + '%'],
      ['90%区间', fmt.price(cp.p10) + '~' + fmt.price(cp.p90)],
      ['成本分离', cp.separation.toFixed(2) + '%'],
    ];
    if (cp.vp) {
      rows.push(['POC 成交峰', fmt.price(cp.vp.poc)]);
      rows.push(['价值区(70%)', fmt.price(cp.vp.val) + '~' + fmt.price(cp.vp.vah)]);
    }
    rows.forEach(function (r) {
      var d = el('div', 'cs');
      d.appendChild(el('span', '', r[0]));
      d.appendChild(el('b', '', r[1]));
      stats.appendChild(d);
    });

    // 集中区
    if (cp.main_zone) {
      var z = el('div', 'zone main');
      var head = el('div', 'zr');
      head.appendChild(el('span', 'zt', '主力筹码集中区'));
      head.appendChild(el('span', 'zp', fmt.price(cp.main_zone.low) + ' ~ ' + fmt.price(cp.main_zone.high)));
      z.appendChild(head);
      z.appendChild(el('div', '', '峰值 ' + fmt.price(cp.main_zone.peak) +
        ' · 区间宽度 ' + cp.main_zone.width_pct.toFixed(1) + '% · 距现价 ' +
        sign((cp.main_zone.peak / cp.price - 1) * 100, 2) + '%'));
      zones.appendChild(z);
    }
    if (cp.retail_zone) {
      var z2 = el('div', 'zone retail');
      var head2 = el('div', 'zr');
      head2.appendChild(el('span', 'zt', '散户筹码集中区'));
      head2.appendChild(el('span', 'zp', fmt.price(cp.retail_zone.low) + ' ~ ' + fmt.price(cp.retail_zone.high)));
      z2.appendChild(head2);
      z2.appendChild(el('div', '', '峰值 ' + fmt.price(cp.retail_zone.peak) +
        ' · 区间宽度 ' + cp.retail_zone.width_pct.toFixed(1) + '% · 距现价 ' +
        sign((cp.retail_zone.peak / cp.price - 1) * 100, 2) + '%'));
      zones.appendChild(z2);
    }
  }

  // ------------------------------------------------------------ 缠论
  function renderChan(ch) {
    var grid = $('chanGrid');
    grid.innerHTML = '';
    var kind = state.data && state.data.kind;
    var isOfund = kind === 'ofund';
    var isGlobal = kind === 'global';
    if (!ch || !ch.ok) {
      $('chanTrend').textContent = '不可用';
      grid.innerHTML = '<div class="cg"><span>缠论</span><b>' +
        (isOfund ? '场外基金不适用' : (isGlobal ? '外围市场不适用' : '数据不足')) + '</b></div>';
      $('sigList').innerHTML = '<div class="sig-empty">' +
        (isOfund ? '场外基金按净值成交，无盘中K线，不做缠论结构分析'
          : (isGlobal ? '外围市场暂不做缠论结构分析（仅做趋势/动量/位置四维评分）'
            : 'K线数量不足，无法进行缠论分析')) + '</div>';
      return;
    }
    var trendCls = ch.trend && ch.trend.indexOf('上涨') >= 0 ? 'up' :
      (ch.trend && ch.trend.indexOf('下跌') >= 0 ? 'down' : '');
    $('chanTrend').textContent = ch.trend || '—';
    $('chanTrend').className = 'tag ' + trendCls;

    var items = [
      ['走势类型', ch.trend || '—'],
      ['中枢位置', (ch.position || '—').replace(/（.*/, '')],
      ['笔数', ch.bi_count],
      ['线段数', ch.duan_count],
      ['中枢数', ch.zs_count],
      ['分型数', ch.fractal_count],
    ];
    if (ch.cur_zs) {
      items.push(['中枢区间', fmt.price(ch.cur_zs.zd) + ' ~ ' + fmt.price(ch.cur_zs.zg)]);
      items.push(['中枢笔数', ch.cur_zs.bi_count]);
    }
    items.forEach(function (it) {
      var d = el('div', 'cg');
      d.appendChild(el('span', '', it[0]));
      d.appendChild(el('b', '', it[1] == null ? '—' : String(it[1])));
      grid.appendChild(d);
    });

    var box = $('sigList');
    box.innerHTML = '';
    var sigs = (ch.signals || []).slice(-8).reverse();
    if (!sigs.length) {
      box.innerHTML = '<div class="sig-empty">近期无缠论买卖点</div>';
      return;
    }
    sigs.forEach(function (s) {
      var d = el('div', 'sig ' + s.side);
      d.appendChild(el('span', 'st', s.type));
      d.appendChild(el('span', 'sd', s.day + ' · ' + (s.desc || '').slice(0, 22)));
      d.appendChild(el('span', 'sp', fmt.price(s.price)));
      box.appendChild(d);
    });
  }

  // ------------------------------------------------------------ 主力阶段
  var PHASES = ['吸筹', '洗盘', '拉升', '派发', '下跌', '横盘'];
  function renderPhase(ph, segs) {
    var bar = $('phaseBar');
    bar.innerHTML = '';
    if (!ph) return;
    var isOfund = state.data && state.data.kind === 'ofund';
    var isGlobal = state.data && state.data.kind === 'global';
    var det = ph.detail || {};
    if (isOfund || isGlobal || !Object.keys(det).length) {
      $('phaseTag').textContent = '不适用';
      $('phaseTag').className = 'tag';
      PHASES.forEach(function (p) {
        bar.appendChild(el('div', 'pb', p + '<span class="pc2">—</span>'));
      });
      $('phaseDesc').textContent = isGlobal
        ? '外围市场不做主力筹码与阶段分析；请参考上方四维评分（当日/趋势/动量/位置）。'
        : '场外基金无成交量与盘中K线，主力阶段识别不适用；请参考上方净值趋势评分。';
      $('phaseFeat').innerHTML = '';
      $('segList').innerHTML = '<div class="sig-empty">无分段数据</div>';
      return;
    }
    PHASES.forEach(function (p) {
      var d = el('div', 'pb' + (ph.phase === p ? ' on' : ''));
      d.innerHTML = p + '<span class="pc2">' + ((det[p] || 0) * 100).toFixed(0) + '%</span>';
      bar.appendChild(d);
    });
    $('phaseTag').textContent = ph.phase + ' ' + (ph.confidence * 100).toFixed(0) + '%';
    $('phaseTag').className = 'tag ' + (['拉升', '吸筹'].indexOf(ph.phase) >= 0 ? 'up' :
      (['下跌', '派发'].indexOf(ph.phase) >= 0 ? 'down' : ''));
    $('phaseDesc').textContent = ph.desc || '';

    var feat = $('phaseFeat');
    feat.innerHTML = '';
    Object.keys(ph.features || {}).forEach(function (k) {
      var v = ph.features[k];
      var d = el('div', 'pf');
      d.appendChild(el('span', '', k));
      d.appendChild(el('b', '', Array.isArray(v) ? v.join(' / ') : String(v)));
      feat.appendChild(d);
    });

    var list = $('segList');
    list.innerHTML = '';
    (segs || []).slice().reverse().forEach(function (s) {
      var d = el('div', 'seg');
      var sp = el('span', 'sph', s.phase);
      sp.style.color = ['拉升', '吸筹'].indexOf(s.phase) >= 0 ? '#ef232a' :
        (['下跌', '派发'].indexOf(s.phase) >= 0 ? '#14b143' : '#8d949c');
      d.appendChild(sp);
      d.appendChild(el('span', 'sdate', s.start_day.slice(2)));
      d.appendChild(el('span', 'svw', fmt.price(s.vwap)));
      var ch = el('span', 'sch', sign(s.chg_pct, 1) + '%');
      ch.style.color = s.chg_pct >= 0 ? '#ef232a' : '#14b143';
      d.appendChild(ch);
      d.title = s.start_day + ' ~ ' + s.end_day + ' · ' + s.days + '个交易日 · 成本 ' + fmt.price(s.vwap);
      list.appendChild(d);
    });
    if (!segs || !segs.length) list.innerHTML = '<div class="sig-empty">无分段数据</div>';
  }

  // ------------------------------------------------------------ 转折点判断
  //
  // 两件事必须说清楚，否则用户会被数字误导：
  //   1. 绝对阈值跨时段不可迁移 → 同时给「分位」（过去 160 根里排第几）
  //   2. 模型命中拐点的准确率只有 30~50% → 把该板块的真实准确率直接摊在卡片上
  function renderTurning(tr) {
    var card = $('turnCard');
    if (!card) return;
    if (!tr || !tr.ok) {
      card.style.display = 'none';
      return;
    }
    card.style.display = '';

    var meta = tr.meta || {};
    var st = tr.state || {};
    var rev = tr.rev || {};

    // 板块标签
    var stag = $('turnSector');
    stag.textContent = (meta.sector || '—') + (meta.fallback ? ' · 兜底' : '');
    stag.className = 'tag ' + (meta.fallback ? '' : 'up');
    stag.title = (meta.how || '') +
      (meta.fallback ? '（该板块未单独标定，用同资金属性平均参数，可信度较低）' : '');

    // 状态行
    var box = $('turnState');
    box.innerHTML = '';
    var sname = st.name || '—';
    var cls = sname.indexOf('涨') >= 0 ? 'up' : (sname.indexOf('跌') >= 0 ? 'down' : '');
    var d1 = el('div', 'ts-main ' + cls, sname);
    box.appendChild(d1);
    box.appendChild(el('div', 'ts-sub',
      '状态分 ' + (st.score >= 0 ? '+' : '') + (st.score != null ? st.score.toFixed(2) : '—') +
      ' · ADX ' + (st.adx != null ? st.adx.toFixed(0) : '—') +
      ' · ATR ' + (st.atr_pct != null ? st.atr_pct.toFixed(2) : '—') + '%' +
      ' · RSI ' + (st.rsi != null ? st.rsi.toFixed(0) : '—')));
    box.appendChild(el('div', 'ts-hint',
      '状态按近 3 个月指标算；下面的「趋势段」按 PS 分段算，时间尺度更长，两者可以不一致'));

    // 两个反转概率条
    var rb = $('turnRev');
    rb.innerHTML = '';
    [['up', '底部反转', '#ef232a'], ['down', '顶部反转', '#14b143']].forEach(function (it) {
      var r = rev[it[0]];
      if (!r) return;
      var row = el('div', 'tr-row');
      row.appendChild(el('span', 'tr-lab', it[1]));

      var bar = el('div', 'tr-bar');
      var fill = el('i', '');
      fill.style.width = Math.max(1, Math.min(100, r.p * 100)).toFixed(1) + '%';
      fill.style.background = it[2];
      if (r.sig) fill.style.boxShadow = '0 0 8px ' + it[2];
      bar.appendChild(fill);
      // 阈值刻度
      var mark = el('b', '');
      mark.style.left = Math.max(0, Math.min(100, r.thr * 100)).toFixed(1) + '%';
      mark.title = '标定阈值 ' + r.thr;
      bar.appendChild(mark);
      row.appendChild(bar);

      var val = el('span', 'tr-val', r.p.toFixed(3));
      val.style.color = it[2];
      row.appendChild(val);

      var pctTxt = (r.pct != null) ? ('分位 ' + (r.pct * 100).toFixed(0) + '%') : '分位 —';
      var pt = el('span', 'tr-pct' + (r.rank_sig ? ' hot' : ''), pctTxt);
      if (r.rank_sig) pt.style.color = it[2];   // 高亮色跟随该行语义，别一律用红
      pt.title = '该概率在过去 ' + 160 + ' 根 K 线里的百分位。≥95% 表示这是近一年最像反转的 5% 时刻';
      row.appendChild(pt);

      rb.appendChild(row);
    });

    // 当前趋势段
    var pb = $('turnPhase');
    pb.innerHTML = '';
    var ph = tr.phase;
    if (ph) {
      var up = ph.type === 'up';
      var tag = el('span', 'tp-tag ' + (up ? 'up' : 'down'),
        (up ? '上涨段' : '下跌段') + ' ' + ph.bars + ' 根');
      pb.appendChild(tag);
      pb.appendChild(el('span', 'tp-txt',
        (ph.start_day || '').slice(2) + ' 起 · 累计 ' +
        (ph.chg >= 0 ? '+' : '') + ph.chg.toFixed(1) + '%'));
    } else {
      pb.appendChild(el('span', 'tp-txt', '趋势段识别数据不足'));
    }

    // 依据
    var ev = $('turnEv');
    ev.innerHTML = '';
    (tr.evidence || []).forEach(function (t) {
      ev.appendChild(el('div', 'tev', '· ' + t));
    });

    // 可信度备注
    var nt = $('turnNote');
    nt.innerHTML = '';
    (tr.note || []).forEach(function (t) {
      nt.appendChild(el('div', 'tn', t));
    });
    if (tr.kind_note) nt.appendChild(el('div', 'tn', tr.kind_note));
  }

  // ------------------------------------------------------------ 形态
  function renderPatterns(p) {
    var box = $('patList');
    box.innerHTML = '';
    var list = (p && p.list) || [];
    $('patCount').textContent = p ? ('多 ' + p.bull + ' / 空 ' + p.bear) : '';
    if (!list.length) {
      box.innerHTML = '<div class="sig-empty">' +
        ((p && p.text) ? p.text : '近期无明确K线形态') + '</div>';
      return;
    }
    list.slice().reverse().forEach(function (x) {
      var d = el('div', 'pt-item');
      var l = el('div', 'l');
      l.style.flexDirection = 'column';
      l.style.alignItems = 'flex-start';
      var r1 = el('div', '', '');
      r1.style.display = 'flex';
      r1.style.gap = '6px';
      r1.style.alignItems = 'center';
      var nm = el('span', 'nm', x.name);
      nm.style.color = x.side === 'bull' ? '#ef232a' : (x.side === 'bear' ? '#14b143' : '#8d949c');
      r1.appendChild(nm);
      r1.appendChild(el('span', 'tagd', x.tag));
      r1.appendChild(el('span', 'tagd', x.day ? x.day.slice(5) : ''));
      l.appendChild(r1);
      l.appendChild(el('div', 'ds', x.desc));
      d.appendChild(l);
      box.appendChild(d);
    });
  }

  // ------------------------------------------------------------ 阶段涨跌
  function renderPerf(sum) {
    var box = $('perf');
    box.innerHTML = '';
    if (!sum || !sum.periods) return;
    var mx = 1;
    Object.keys(sum.periods).forEach(function (k) {
      var v = sum.periods[k];
      if (v != null && Math.abs(v) > mx) mx = Math.abs(v);
    });
    Object.keys(sum.periods).forEach(function (k) {
      var v = sum.periods[k];
      if (v == null) return;
      var row = el('div', 'pf-row');
      row.appendChild(el('div', 'pk', k));
      var bar = el('div', 'pb2');
      bar.appendChild(el('div', 'm'));
      var f = el('div', 'f');
      var w = Math.min(50, Math.abs(v) / mx * 50);
      f.style.width = w + '%';
      if (v >= 0) { f.style.left = '50%'; f.style.background = '#ef232a'; }
      else { f.style.left = (50 - w) + '%'; f.style.background = '#14b143'; }
      bar.appendChild(f);
      row.appendChild(bar);
      var pv = el('div', 'pv', sign(v, 2) + '%');
      pv.style.color = v >= 0 ? '#ef232a' : '#14b143';
      row.appendChild(pv);
      box.appendChild(row);
    });
    if (sum.mdd != null) {
      var row2 = el('div', 'pf-row');
      row2.appendChild(el('div', 'pk', '最大回撤'));
      row2.appendChild(el('div', 'pb2', ''));
      var pv2 = el('div', 'pv', '-' + sum.mdd.toFixed(2) + '%');
      pv2.style.color = '#14b143';
      row2.appendChild(pv2);
      box.appendChild(row2);
    }
  }

  // ------------------------------------------------------------ 自选
  function renderWatch() {
    api('/api/watch').then(function (d) {
      if (!d.ok) return;
      var box = $('watchlist');
      box.innerHTML = '';
      (d.watch || []).forEach(function (sym) {
        var q = (d.quotes || {})[sym] || {};
        var item = el('div', 'wl-item' + (sym === state.code ? ' on' : ''));
        var r1 = el('div', 'r1');
        r1.appendChild(el('span', 'nm', q.name || sym.toUpperCase()));
        var pc = q.change_pct || 0;
        var s = el('span', 'pc ' + colorOf(pc), sign(pc, 2) + '%');
        r1.appendChild(s);
        item.appendChild(r1);
        var r2 = el('div', 'r2');
        r2.appendChild(el('span', 'cd2', sym.toUpperCase()));
        var pr = el('span', 'pr ' + colorOf(pc), fmt.price(q.price || 0));
        r2.appendChild(pr);
        item.appendChild(r2);
        item.onclick = function () {
          if (state.code === sym) return;
          load(sym, state.scale);
        };
        item.ondblclick = function (e) {
          e.stopPropagation();
          if (!confirm('从自选中删除 ' + (q.name || sym) + ' ?')) return;
          api('/api/watch?action=remove&code=' + sym).then(renderWatch);
        };
        box.appendChild(item);
      });
      if (!(d.watch || []).length) {
        box.innerHTML = '<div class="sig-empty" style="padding:20px 10px">暂无自选</div>';
      }
    });
  }

  // ------------------------------------------------------------ 板块 / 排行
  function loadSectors() {
    api('/api/sectors').then(function (d) {
      if (!d.ok) return;
      var box = $('sectorList');
      box.innerHTML = '';
      var items = (d.items || []).slice(0, 14);
      var mx = 1;
      items.forEach(function (x) { if (Math.abs(x.change_pct) > mx) mx = Math.abs(x.change_pct); });
      items.forEach(function (x) {
        var row = el('div', 'sr-item');
        var l = el('div', 'l');
        l.appendChild(el('span', 'n', x.name));
        var bar = el('div', 'bar-mini');
        var i = el('i');
        i.style.width = Math.min(100, Math.abs(x.change_pct) / mx * 100) + '%';
        i.style.background = x.change_pct >= 0 ? '#ef232a' : '#14b143';
        bar.appendChild(i);
        l.appendChild(bar);
        row.appendChild(l);
        var v = el('span', 'v ' + colorOf(x.change_pct), sign(x.change_pct, 2) + '%');
        row.appendChild(v);
        row.title = x.name + ' · 领涨 ' + x.lead_name + ' ' + sign(x.lead_change_pct, 2) + '%';
        row.onclick = function () { load(x.lead_symbol, 240); };
        box.appendChild(row);
      });
      $('sectorTime').textContent = items.length + ' 个行业';
    });
  }

  function loadRank() {
    api('/api/rank?sort=changepercent&num=15').then(function (d) {
      if (!d.ok) return;
      var box = $('rankList');
      box.innerHTML = '';
      (d.items || []).slice(0, 15).forEach(function (x) {
        var row = el('div', 'rk-item');
        var l = el('div', 'l');
        l.appendChild(el('span', 'n', x.name));
        l.appendChild(el('span', 'cd2', x.symbol.toUpperCase()));
        row.appendChild(l);
        var v = el('span', 'v ' + colorOf(x.changepercent), sign(x.changepercent, 2) + '%');
        row.appendChild(v);
        row.onclick = function () { load(x.symbol, 240); };
        box.appendChild(row);
      });
    });
  }

  // ------------------------------------------------------------ 搜索
  function doSearch(q) {
    if (!q) { $('suggest').classList.remove('show'); return; }
    api('/api/search?q=' + encodeURIComponent(q)).then(function (d) {
      var box = $('suggest');
      box.innerHTML = '';
      state.suggestList = (d.items || []);
      state.suggestIdx = -1;
      if (!state.suggestList.length) {
        box.classList.remove('show');
        return;
      }
      state.suggestList.forEach(function (it, i) {
        var row = el('div', 'si');
        row.appendChild(el('span', '', it.name));
        row.appendChild(el('span', 'c', it.symbol.toUpperCase()));
        row.onmousedown = function (e) {
          e.preventDefault();
          pick(it.symbol);
        };
        box.appendChild(row);
      });
      box.classList.add('show');
    });
  }

  function pick(sym) {
    $('suggest').classList.remove('show');
    $('q').value = '';
    closeList();
    load(sym, state.scale, false, true);
    api('/api/watch?action=add&code=' + sym).then(renderWatch);
  }

  // ------------------------------------------------------------ 状态
  function pollStatus() {
    api('/api/status').then(function (s) {
      state.status = s;
      state.retry = 0;
      var dot = $('dot');
      dot.className = 'dot ' + (s.errors > 0 && s.rounds === 0 ? 'err' : 'ok');
      $('statustext').textContent = '已轮询 ' + s.rounds + ' 次 · ' + s.last_ms + 'ms';
      var pct = Math.max(0, Math.min(1, 1 - s.next_in / s.interval));
      var ring = $('ringfg');
      if (ring) {
        ring.style.strokeDasharray = 50.3;
        ring.style.strokeDashoffset = 50.3 * (1 - pct);
      }
      $('countdown').textContent = Math.max(0, s.next_in).toFixed(0) + 's';

      if (s.rounds !== state.lastRound) {
        var first = state.lastRound < 0;
        state.lastRound = s.rounds;
        if (!first) {
          load(null, null, true);
          loadGlobal();
        }
      }
    }).catch(function () {
      state.retry = (state.retry || 0) + 1;
      $('dot').className = 'dot err';
      $('statustext').textContent = '连接中断，正在重连…(' + state.retry + ')';
      // 服务重启后自动恢复：指数退避重试
      if (state.retry <= 30) {
        setTimeout(function () { load(state.code, state.scale, true); }, 1500);
      }
    });
  }

  function loadIndices() {
    api('/api/indices').then(function (d) {
      if (!d.ok) return;
      var box = $('indexbar');
      box.innerHTML = '';
      var order = ['sh000001', 'sz399001', 'sz399006', 'sh000688'];
      order.forEach(function (k) {
        var q = d.items[k];
        if (!q) return;
        var ix = el('div', 'ix');
        ix.appendChild(el('span', 'n', q.name));
        ix.appendChild(el('span', 'p ' + colorOf(q.change_pct), fmt.price(q.price)));
        ix.appendChild(el('span', 'c ' + colorOf(q.change_pct),
          sign(q.change) + '  ' + sign(q.change_pct, 2) + '%'));
        box.appendChild(ix);
      });
    });
  }

  // ------------------------------------------------------------ 事件
  function bind() {
    $('go').onclick = function () {
      var v = $('q').value.trim();
      if (v) pick(v);
    };
    $('q').addEventListener('input', function (e) {
      clearTimeout(state.searchTimer);
      var v = e.target.value.trim();
      state.searchTimer = setTimeout(function () { doSearch(v); }, 260);
    });
    $('q').addEventListener('keydown', function (e) {
      var box = $('suggest');
      if (!box.classList.contains('show')) {
        if (e.key === 'Enter') { var v = $('q').value.trim(); if (v) pick(v); }
        return;
      }
      var items = box.querySelectorAll('.si');
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        state.suggestIdx += (e.key === 'ArrowDown' ? 1 : -1);
        if (state.suggestIdx < 0) state.suggestIdx = items.length - 1;
        if (state.suggestIdx >= items.length) state.suggestIdx = 0;
        items.forEach(function (x, i) { x.classList.toggle('act', i === state.suggestIdx); });
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (state.suggestIdx >= 0 && state.suggestList[state.suggestIdx]) {
          pick(state.suggestList[state.suggestIdx].symbol);
        } else if (state.suggestList.length) {
          // 没选中具体项时，默认取第一条建议
          pick(state.suggestList[0].symbol);
        } else {
          var v2 = $('q').value.trim();
          if (v2) pick(v2);
        }
      } else if (e.key === 'Escape') {
        box.classList.remove('show');
      }
    });
    document.addEventListener('click', function (e) {
      if (!e.target.closest('.searchbox')) $('suggest').classList.remove('show');
    });

    // 周期
    document.querySelectorAll('#scaleTabs button').forEach(function (b) {
      b.onclick = function () {
        var sc = parseInt(b.dataset.scale, 10);
        if (state.data && state.data.kind === 'global' && sc !== 240) {
          alert('外围市场（美股/港股/外汇/商品）目前只提供日线数据');
          return;
        }
        document.querySelectorAll('#scaleTabs button').forEach(function (x) {
          x.classList.remove('on');
        });
        b.classList.add('on');
        load(null, sc);
      };
    });

    // 全屏
    $('btnFullscreen').onclick = toggleFullscreen;

    // 副图
    document.querySelectorAll('#subTabs button').forEach(function (b) {
      b.onclick = function () {
        document.querySelectorAll('#subTabs button').forEach(function (x) {
          x.classList.remove('on');
        });
        b.classList.add('on');
        state.chart.setOption('sub', b.dataset.sub);
      };
    });

    // 指标开关
    $('tMA').onchange = function (e) { state.chart.setOption('ma', e.target.checked); };
    $('tBOLL').onchange = function (e) { state.chart.setOption('boll', e.target.checked); };
    $('tCHAN').onchange = function (e) { state.chart.setOption('chan', e.target.checked); };
    $('tCHIP').onchange = function (e) { state.chart.setOption('chip', e.target.checked); };
    $('tSIG').onchange = function (e) { state.chart.setOption('sig', e.target.checked); };

    // 导航
    document.querySelectorAll('.nav a').forEach(function (a) {
      a.onclick = function () {
        document.querySelectorAll('.nav a').forEach(function (x) { x.classList.remove('on'); });
        a.classList.add('on');
        var k = a.dataset.nav;
        if (k === 'about') { alert(ABOUT); return; }
        if (k === 'global') { openGlobal(); return; }
        openList(k);
      };
    });

    // 列表视图
    $('lvClose').onclick = function () { closeList(true); };

    // 全球市场弹层
    $('graiChip').onclick = openGlobal;
    $('gmodalClose').onclick = closeGlobal;
    $('gmask').onclick = closeGlobal;

    document.addEventListener('keydown', function (e) {
      var tag = (e.target && e.target.tagName) || '';
      var typing = tag === 'INPUT' || tag === 'TEXTAREA';
      // Alt+← 返回上一页
      if (e.altKey && e.key === 'ArrowLeft') {
        e.preventDefault();
        goBack();
        return;
      }
      if (e.key === 'Escape') {
        if (document.querySelector('.chartcard.fullscreen')) { toggleFullscreen(false); return; }
        closeList(); closeGlobal();
        return;
      }
      if (!typing && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
        toggleFullscreen();
      }
    });
  }

  var ABOUT = '交易很轻松 v1.0\n\n'
    + '· 数据：新浪财经实时行情、日/分钟K线、行业板块、场外基金净值（20秒轮询）\n'
    + '· 指标：兼容 pandas-ta 命名的指标库（SMA/EMA/RSI/MACD/BBANDS/ATR/ADX/KDJ/OBV/CMF/MFI/Supertrend…）\n'
    + '· 缠论：包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点\n'
    + '· 筹码：CYQ 三角分布 + 换手衰减双层模型（主力层 / 散户层）\n'
    + '· 主力：威科夫阶段识别（吸筹/洗盘/拉升/派发/下跌/横盘）+ 各阶段成交量加权成本\n'
    + '· 评分：TRS 趋势共振评分，七维 tanh 软饱和加权\n\n'
    + '仅供量化研究与学习，不构成投资建议。';

  // ------------------------------------------------------------ 启动
  function boot() {
    initChart();
    bind();
    var hash = (location.hash || '').replace('#', '');
    var start = hash || localStorage.getItem('jq_code') || 'sh600519';
    updateBackBtn();
    if (hash.indexOf('list/') === 0) {
      applyRoute();
    } else {
      load(start, 240);
      localStorage.setItem('jq_code', start);
    }
    loadIndices();
    loadGlobal();
    loadSectors();
    loadRank();
    pollStatus();
    setInterval(pollStatus, 1000);
    setInterval(loadIndices, 5000);
    setInterval(loadGlobal, 5000);
    setInterval(loadSectors, 60000);
    setInterval(loadRank, 45000);

    // 记录当前代码
    // ---------------- 路由绑定
    rawLoad = load;
    load = function (code, scale, silent, push) {
      if (code) {
        localStorage.setItem('jq_code', code);
        state.code = code;
        state.listKey = null;
      }
      var ret = rawLoad(code, scale, silent);
      if (code) syncHash(!!push);
      return ret;
    };

    window.addEventListener('popstate', applyRoute);
    window.addEventListener('hashchange', function () {
      var h = (location.hash || '').replace(/^#/, '');
      if (!h) return;
      if (h.indexOf('list/') === 0) {
        if (!state.listKey) applyRoute();
      } else if (h !== state.code) {
        applyRoute();
      }
    });

    $('btnBack').onclick = goBack;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
