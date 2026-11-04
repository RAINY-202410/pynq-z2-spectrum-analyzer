(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const API_BASE = window.BX_API_BASE || "";
  const R4_CONTROL_TOKEN = window.R4_CONTROL_TOKEN || "";
  const PAGE_PARAMS = new URLSearchParams(window.location.search);
  const DATA_SOURCE = PAGE_PARAMS.get("source") === "user" ? "user" : "demo";
  const RECORD_ID = PAGE_PARAMS.get("record_id") || "";
  const apiURL = (url) => {
    if (!url.startsWith("/api/")) return url;
    if (DATA_SOURCE !== "user") return API_BASE + url;
    const parsed = new URL(url, window.location.origin);
    let mapped;
    if (parsed.pathname === "/api/replay/index") {
      mapped = "/bx/api/user-analysis/index";
    } else if (parsed.pathname === "/api/replay/frame") {
      mapped = "/bx/api/user-analysis/frame";
    } else if (parsed.pathname === "/api/replay/trend") {
      mapped = "/bx/api/user-analysis/trend";
    } else if (parsed.pathname === "/api/export") {
      mapped = "/bx/api/user-analysis/export";
    } else {
      throw new Error("用户记录不支持该 API：" + parsed.pathname);
    }
    parsed.searchParams.set("record_id", RECORD_ID);
    return mapped + (parsed.search ? "?" + parsed.searchParams.toString() : "");
  };
  const sourceLabel = () => DATA_SOURCE === "user" ? "用户记录" : "演示样例";
  const ui = {
    runSelect: $("runSelect"),
    modeSelect: $("modeSelect"),
    speedSelect: $("speedSelect"),
    rangeSelect: $("rangeSelect"),
    prevBtn: $("prevBtn"),
    playBtn: $("playBtn"),
    nextBtn: $("nextBtn"),
    statusText: $("statusText"),
    modeHint: $("modeHint"),
    sourceBadge: $("sourceBadge"),
    runName: $("runName"),
    frameText: $("frameText"),
    sampleIndexText: $("sampleIndexText"),
    sequenceText: $("sequenceText"),
    elapsedText: $("elapsedText"),
    windowText: $("windowText"),
    fsText: $("fsText"),
    peakReadout: $("peakReadout"),
    spectrumCanvas: $("spectrumCanvas"),
    waterfallCanvas: $("waterfallCanvas"),
    timelineCanvas: $("timelineCanvas"),
    gapPanel: $("gapPanel"),
    gapTitle: $("gapTitle"),
    gapDetail: $("gapDetail"),
    gapWait: $("gapWait"),
    sampleTableBody: $("sampleTableBody"),
    runMetricRows: $("runMetricRows"),
    runSavedSamples: $("runSavedSamples"),
    shownSamples: $("shownSamples"),
    uniqueSamples: $("uniqueSamples"),
    cursorToggle: $("cursorToggle"),
    cursorCurveSelect: $("cursorCurveSelect"),
    cursorABtn: $("cursorABtn"),
    cursorBBtn: $("cursorBBtn"),
    dualDemoBtn: $("dualDemoBtn"),
    cursorAFreq: $("cursorAFreq"),
    cursorABin: $("cursorABin"),
    cursorALinear: $("cursorALinear"),
    cursorADbfs: $("cursorADbfs"),
    cursorBFreq: $("cursorBFreq"),
    cursorBBin: $("cursorBBin"),
    cursorBLinear: $("cursorBLinear"),
    cursorBDbfs: $("cursorBDbfs"),
    cursorDeltaF: $("cursorDeltaF"),
    cursorDeltaDb: $("cursorDeltaDb"),
    cursorRatio: $("cursorRatio"),
    rangeLabel: $("rangeLabel"),
    showCurrent: $("showCurrent"),
    showAverage: $("showAverage"),
    showHold: $("showHold"),
    averageLengthSelect: $("averageLengthSelect"),
    clearFeaturesBtn: $("clearFeaturesBtn"),
    featureAverageCount: $("featureAverageCount"),
    featureHoldCount: $("featureHoldCount"),
    featureAverageRange: $("featureAverageRange"),
    featureHoldRange: $("featureHoldRange"),
    featureZeroBins: $("featureZeroBins"),
    featureResetState: $("featureResetState"),
    featureAverageInline: $("featureAverageInline"),
    featureHoldInline: $("featureHoldInline"),
    featureAverageRangeInline: $("featureAverageRangeInline"),
    featureHoldRangeInline: $("featureHoldRangeInline"),
    featureZeroInline: $("featureZeroInline"),
    featureStateInline: $("featureStateInline"),
    trendMode: $("trendMode"),
    trendTarget: $("trendTarget"),
    trendBandwidth: $("trendBandwidth"),
    trendThreshold: $("trendThreshold"),
    trendHysteresis: $("trendHysteresis"),
    trendMinConsecutive: $("trendMinConsecutive"),
    trendMaxGap: $("trendMaxGap"),
    trendMinHz: $("trendMinHz"),
    trendMaxHz: $("trendMaxHz"),
    trendApplyBtn: $("trendApplyBtn"),
    exportBtn: $("exportBtn"),
    trendStatus: $("trendStatus"),
    trendContext: $("trendContext"),
    trendCanvas: $("trendCanvas"),
    trendPointCount: $("trendPointCount"),
    trendValidCount: $("trendValidCount"),
    trendMissingCount: $("trendMissingCount"),
    trendGapCount: $("trendGapCount"),
    trendEventCount: $("trendEventCount"),
    eventList: $("eventList"),
    exportResult: $("exportResult"),
  };

  const S = {
    index: null,
    runs: [],
    run: null,
    samples: [],
    currentIdx: -1,
    frame: null,
    playing: false,
    timer: null,
    requestToken: 0,
    mode: "original",
    speed: 20,
    rangeHz: 24000,
    waterfall: new Map(),
    cursors: { A: null, B: null },
    activeCursor: "A",
    cursorCurve: "current",
    cursorLocked: false,
    stats: { shown: 0, firstElapsed: null, lastElapsed: null },
    plotBounds: null,
    trend: null,
    averageLength: 8,
    showCurrent: true,
    showAverage: true,
    showHold: true,
    feature: {
      frames: [],
      seen: new Set(),
      hold: null,
      holdCount: 0,
      holdStart: null,
      holdEnd: null,
      average: null,
      averageCount: 0,
      averageStart: null,
      averageEnd: null,
      zeroAverage: 0,
      zeroHold: 0,
      resetReason: "等待留样",
      duplicateIgnored: false,
    },
  };

  const COLORS = {
    grid: "rgba(151, 166, 184, 0.16)",
    gridStrong: "rgba(151, 166, 184, 0.28)",
    text: "#97a6b8",
    bright: "#e7edf5",
    accent: "#5eead4",
    amber: "#fbbf24",
    danger: "#fb7185",
  };

  if (DATA_SOURCE === "user") {
    document.title = "我的频谱分析记录";
    const eyebrow = document.querySelector(".eyebrow");
    const heading = document.querySelector(".hero h1");
    const subtitle = document.querySelector(".subtitle");
    const badges = document.querySelectorAll(".hero-badges .badge");
    if (eyebrow) eyebrow.textContent = "用户保存的实时分析";
    if (heading) heading.textContent = "我的频谱分析记录";
    if (subtitle) subtitle.textContent = "当前用户实时采集 · 多帧回放 · 平均/保持 · A/B 游标 · 趋势";
    if (badges[0]) badges[0].textContent = "用户记录";
    if (badges[1]) badges[1].textContent = "来源：当前实时采集";
    if (badges[2]) badges[2].textContent = "非演示数据";
  }

  function fmtTime(value) {
    return Number(value).toFixed(3) + " s";
  }

  function fmtShort(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n.toFixed(2) + " s";
  }

  function fmtHz(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n >= 1000 ? (n / 1000).toFixed(3) + " kHz" : n.toFixed(1) + " Hz";
  }

  function fmtDb(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) + " dBFS" : "—";
  }

  function escapeHtml(value) {
    return String(value == null ? "—" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setStatus(text) {
    ui.statusText.textContent = text;
  }

  function dbFromLinear(linear) {
    return Array.from(linear, (value) => 20 * Math.log10(Math.max(Number(value), 1e-12)));
  }

  function featureRange(start, end) {
    if (!start || !end) return "—";
    return "frame " + start.frame_id + " (" + fmtShort(start.elapsed_s) + ") → " +
      "frame " + end.frame_id + " (" + fmtShort(end.elapsed_s) + ")";
  }

  function resetFeatures(reason) {
    S.feature = {
      frames: [],
      seen: new Set(),
      hold: null,
      holdCount: 0,
      holdStart: null,
      holdEnd: null,
      average: null,
      averageCount: 0,
      averageStart: null,
      averageEnd: null,
      zeroAverage: 0,
      zeroHold: 0,
      resetReason: reason,
      duplicateIgnored: false,
    };
    renderFeatureStats();
    renderSpectrum();
  }

  function updateFeatureAverage() {
    const frames = S.feature.frames;
    const count = Math.min(S.averageLength, frames.length);
    if (!count) {
      S.feature.average = null;
      S.feature.averageCount = 0;
      S.feature.averageStart = null;
      S.feature.averageEnd = null;
      S.feature.zeroAverage = 0;
      return;
    }
    const recent = frames.slice(-count);
    const points = recent[0].amplitude.length;
    const average = new Float64Array(points);
    recent.forEach((item) => {
      for (let i = 0; i < points; i += 1) {
        average[i] += item.amplitude[i] * item.amplitude[i];
      }
    });
    for (let i = 0; i < points; i += 1) {
      average[i] = Math.sqrt(average[i] / count);
    }
    let zero = 0;
    for (let i = 0; i < points; i += 1) {
      if (average[i] === 0) zero += 1;
    }
    S.feature.average = average;
    S.feature.averageCount = count;
    S.feature.averageStart = recent[0];
    S.feature.averageEnd = recent[recent.length - 1];
    S.feature.zeroAverage = zero;
  }

  function updateFeatures(frame) {
    const key = String(frame.frame_id);
    if (S.feature.seen.has(key)) {
      S.feature.duplicateIgnored = true;
      return false;
    }
    const amplitude = Float64Array.from(frame.amplitude || []);
    if (!amplitude.length) return false;
    if (S.feature.frames.length >= 32) {
      const old = S.feature.frames.shift();
      S.feature.seen.delete(String(old.frame_id));
    }
    const record = {
      frame_id: frame.frame_id,
      sequence: frame.sequence,
      elapsed_s: frame.elapsed_s,
      amplitude,
    };
    S.feature.frames.push(record);
    S.feature.seen.add(key);
    S.feature.holdCount += 1;
    if (S.feature.hold === null) {
      S.feature.hold = new Float64Array(amplitude);
      S.feature.holdStart = record;
    } else {
      for (let i = 0; i < amplitude.length; i += 1) {
        if (amplitude[i] > S.feature.hold[i]) S.feature.hold[i] = amplitude[i];
      }
    }
    S.feature.holdEnd = record;
    let zero = 0;
    for (let i = 0; i < S.feature.hold.length; i += 1) {
      if (S.feature.hold[i] === 0) zero += 1;
    }
    S.feature.zeroHold = zero;
    updateFeatureAverage();
    S.feature.duplicateIgnored = false;
    return true;
  }

  function renderFeatureStats() {
    const feature = S.feature;
    const averageCount = (feature.averageCount || 0) + " / " + S.averageLength;
    const holdCount = String(feature.holdCount || 0);
    const averageRange = featureRange(feature.averageStart, feature.averageEnd);
    const holdRange = featureRange(feature.holdStart, feature.holdEnd);
    const zeroBins = "平均 " + (feature.zeroAverage || 0) + " · 保持 " + (feature.zeroHold || 0);
    const state = (feature.frames.length ? "累计中" : feature.resetReason) +
      (feature.duplicateIgnored ? " · 重复帧已忽略" : "");
    ui.featureAverageCount.textContent = averageCount;
    ui.featureHoldCount.textContent = holdCount;
    ui.featureAverageRange.textContent = averageRange;
    ui.featureHoldRange.textContent = holdRange;
    ui.featureZeroBins.textContent = zeroBins;
    ui.featureResetState.textContent = state;
    ui.featureAverageInline.textContent = averageCount;
    ui.featureHoldInline.textContent = holdCount;
    ui.featureAverageRangeInline.textContent = averageRange;
    ui.featureHoldRangeInline.textContent = holdRange;
    ui.featureZeroInline.textContent = zeroBins;
    ui.featureStateInline.textContent = state;
  }

  async function fetchJSON(url, options) {
    const request = Object.assign({ cache: "no-store" }, options || {});
    if (options && options.headers) {
      request.headers = Object.assign({}, options.headers);
    }
    if (R4_CONTROL_TOKEN) {
      request.headers = Object.assign({}, request.headers || {}, {
        "X-Spectrum-Token": R4_CONTROL_TOKEN,
      });
    }
    const response = await fetch(apiURL(url), request);
    let data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error("服务器返回了无效 JSON");
    }
    if (!response.ok) {
      throw new Error(data.error || ("HTTP " + response.status));
    }
    return data;
  }

  function fillSelect(select, options, valueOf, labelOf) {
    select.innerHTML = "";
    options.forEach((item) => {
      const option = document.createElement("option");
      option.value = valueOf(item);
      option.textContent = labelOf(item);
      select.appendChild(option);
    });
  }

  function setModeHint() {
    if (S.mode === "original") {
      ui.modeHint.textContent = "原始时间轴：间距按 elapsed_s 比例缩放，速度不改变原始时间标签";
    } else {
      ui.modeHint.textContent = "等间隔浏览：非原始时间轴；原始 elapsed_s 仍保留在读数中";
    }
  }

  function updateControls() {
    const hasSamples = S.samples.length > 0;
    const atStart = S.currentIdx <= 0;
    const atEnd = S.currentIdx >= S.samples.length - 1;
    ui.playBtn.disabled = !hasSamples;
    ui.prevBtn.disabled = !hasSamples || atStart;
    ui.nextBtn.disabled = !hasSamples || atEnd;
    ui.playBtn.textContent = S.playing ? "暂停" : (atEnd ? "重新播放" : "播放");
    ui.rangeLabel.textContent = "0–" + (S.rangeHz / 1000) + " kHz";
    ui.clearFeaturesBtn.disabled = S.feature.frames.length === 0;
    ui.exportBtn.disabled = !S.frame;
  }

  function clearTimer() {
    if (S.timer !== null) {
      clearTimeout(S.timer);
      S.timer = null;
    }
  }

  function pause(reason) {
    S.playing = false;
    clearTimer();
    S.requestToken++;
    ui.gapWait.textContent = "";
    updateControls();
    if (reason) setStatus(reason);
  }

  function resetPass() {
    pause("");
    S.waterfall.clear();
    S.stats = { shown: 0, firstElapsed: null, lastElapsed: null };
    S.currentIdx = -1;
    S.frame = null;
    resetCursors("");
    resetFeatures("新一轮播放");
  }

  function prepareCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(280, rect.width || 800);
    const height = Math.max(80, rect.height || 240);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { ctx, width, height };
  }

  function maxIndexForRange(frequency, rangeHz) {
    let index = 0;
    for (let i = 0; i < frequency.length; i += 1) {
      if (frequency[i] <= rangeHz) index = i;
      else break;
    }
    return index;
  }

  function colorForDb(db) {
    const n = Math.max(-120, Math.min(0, Number(db)));
    const t = (n + 120) / 120;
    const hue = 225 - 225 * t;
    const light = 16 + 46 * t;
    return "hsl(" + hue.toFixed(1) + ", 82%, " + light.toFixed(1) + "%)";
  }

  function fmtLinear(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toPrecision(6) : "—";
  }

  function nearestBin(frequency, target) {
    let best = 0;
    let bestDistance = Infinity;
    for (let i = 0; i < frequency.length; i += 1) {
      const distance = Math.abs(Number(frequency[i]) - Number(target));
      if (distance < bestDistance) {
        best = i;
        bestDistance = distance;
      }
    }
    return best;
  }

  function cursorCurveData() {
    if (!S.frame) return null;
    if (S.cursorCurve === "current") {
      return { name: "当前谱", linear: S.frame.amplitude, dbfs: S.frame.dbfs };
    }
    if (S.cursorCurve === "average") {
      if (!S.feature.average) return null;
      return {
        name: "均方幅度平均谱",
        linear: S.feature.average,
        dbfs: dbFromLinear(S.feature.average),
      };
    }
    if (S.cursorCurve === "hold") {
      if (!S.feature.hold) return null;
      return {
        name: "峰值保持",
        linear: S.feature.hold,
        dbfs: dbFromLinear(S.feature.hold),
      };
    }
    return null;
  }

  function cursorReading(key) {
    const bin = S.cursors[key];
    const data = cursorCurveData();
    if (bin === null || !S.frame || !data) {
      return { key, valid: false, bin: bin, curve: data ? data.name : "未累计" };
    }
    const index = Math.min(Math.max(0, Number(bin)), S.frame.frequency_hz.length - 1);
    return {
      key,
      valid: true,
      bin: index,
      frequency: Number(S.frame.frequency_hz[index]),
      linear: Number(data.linear[index]),
      dbfs: Number(data.dbfs[index]),
      curve: data.name,
    };
  }

  function signed(value, digits, suffix) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return (n >= 0 ? "+" : "") + n.toFixed(digits) + suffix;
  }

  function updateCursorReadings() {
    const a = cursorReading("A");
    const b = cursorReading("B");
    const data = cursorCurveData();
    ui.cursorAFreq.textContent = a.valid ? fmtHz(a.frequency) : "—";
    ui.cursorABin.textContent = a.valid ? "bin " + a.bin : "bin —";
    ui.cursorALinear.textContent = a.valid ? "线性 " + fmtLinear(a.linear) : "线性 —";
    ui.cursorADbfs.textContent = a.valid ? "dBFS " + fmtDb(a.dbfs) : "dBFS —";
    ui.cursorBFreq.textContent = b.valid ? fmtHz(b.frequency) : "—";
    ui.cursorBBin.textContent = b.valid ? "bin " + b.bin : "bin —";
    ui.cursorBLinear.textContent = b.valid ? "线性 " + fmtLinear(b.linear) : "线性 —";
    ui.cursorBDbfs.textContent = b.valid ? "dBFS " + fmtDb(b.dbfs) : "dBFS —";
    if (!data) {
      ui.cursorDeltaF.textContent = "未累计";
      ui.cursorDeltaDb.textContent = "未累计";
      ui.cursorRatio.textContent = "未累计";
      return;
    }
    if (!a.valid || !b.valid) {
      ui.cursorDeltaF.textContent = "—";
      ui.cursorDeltaDb.textContent = "—";
      ui.cursorRatio.textContent = "—";
      return;
    }
    ui.cursorDeltaF.textContent = signed(b.frequency - a.frequency, 1, " Hz");
    ui.cursorDeltaDb.textContent = signed(b.dbfs - a.dbfs, 2, " dB");
    if (a.linear > 0 && b.linear > 0) {
      const ratio = b.linear / a.linear;
      const ratioDb = 20 * Math.log10(ratio);
      ui.cursorRatio.textContent = "×" + ratio.toPrecision(5) + " (" + signed(ratioDb, 2, " dB") + ")";
    } else {
      ui.cursorRatio.textContent = "不适用（零幅度）";
    }
  }

  function updateCursorButtons() {
    ui.cursorABtn.classList.toggle("active", S.activeCursor === "A");
    ui.cursorBBtn.classList.toggle("active", S.activeCursor === "B");
  }

  function resetCursors(reason) {
    S.cursors = { A: null, B: null };
    S.activeCursor = "A";
    S.cursorLocked = false;
    ui.cursorToggle.checked = false;
    updateCursorButtons();
    updateCursorReadings();
    renderSpectrum();
    if (reason) setStatus(reason);
  }

  function trendParams() {
    const number = (element, name) => {
      const value = Number(element.value);
      if (!Number.isFinite(value)) throw new Error(name + " 不是有效数字");
      return value;
    };
    const integer = (element, name) => {
      const value = Number(element.value);
      if (!Number.isFinite(value) || Math.round(value) !== value || value < 1) {
        throw new Error(name + " 必须是正整数");
      }
      return value;
    };
    const params = {
      mode: ui.trendMode.value,
      threshold_dbfs: number(ui.trendThreshold, "阈值"),
      hysteresis_db: number(ui.trendHysteresis, "迟滞"),
      min_consecutive: integer(ui.trendMinConsecutive, "连续帧"),
      recover_consecutive: integer(ui.trendMinConsecutive, "恢复帧"),
      max_gap_s: number(ui.trendMaxGap, "最大间隔"),
    };
    if (params.max_gap_s <= 0) throw new Error("最大间隔必须大于 0");
    if (params.mode === "target_band") {
      params.target_hz = number(ui.trendTarget, "目标频率");
      params.bandwidth_hz = number(ui.trendBandwidth, "带宽");
      if (params.bandwidth_hz <= 0) throw new Error("带宽必须大于 0");
    }
    const minText = ui.trendMinHz.value.trim();
    const maxText = ui.trendMaxHz.value.trim();
    if (minText || maxText) {
      if (!minText || !maxText) throw new Error("频率上下限必须同时填写");
      params.min_hz = number(ui.trendMinHz, "频率下限");
      params.max_hz = number(ui.trendMaxHz, "频率上限");
      if (params.min_hz >= params.max_hz) throw new Error("频率下限必须小于上限");
    }
    return params;
  }

  function updateTrendModeControls() {
    const targetMode = ui.trendMode.value === "target_band";
    ui.trendTarget.disabled = !targetMode;
    ui.trendBandwidth.disabled = !targetMode;
  }

  function curveDisplayName() {
    return ({
      current: "当前谱",
      average: "均方幅度平均谱",
      hold: "峰值保持",
    })[S.cursorCurve] || "当前谱";
  }

  function renderTrendContext() {
    if (!S.run) {
      ui.trendContext.textContent = "请先选择实验记录，再加载趋势参数。";
      return;
    }
    const sparse = S.run.saved_samples < S.run.metric_rows;
    const trange = S.feature.averageStart && S.feature.averageEnd
      ? featureRange(S.feature.averageStart, S.feature.averageEnd)
      : "—";
    ui.trendContext.textContent =
      sourceLabel() + " · " + S.run.label + " · " + S.run.window +
      " · fs " + fmtHz(S.run.fs_hz || 0) + " · 指标 " + S.run.metric_rows +
      " · 完整留样 " + S.run.saved_samples + (sparse ? " · 稀疏留样（非连续音频）" : "") +
      " · 测量曲线 " + curveDisplayName() + " · 平均范围 " + trange;
  }

  async function loadTrend() {
    if (!S.run) return;
    let params;
    try {
      params = trendParams();
    } catch (error) {
      ui.trendStatus.textContent = "参数错误";
      ui.trendContext.textContent = error.message;
      return;
    }
    params.run_id = S.run.run_id;
    ui.trendStatus.textContent = "趋势加载中…";
    try {
      const query = new URLSearchParams(params).toString();
      const payload = await fetchJSON("/api/replay/trend?" + query);
      S.trend = payload;
      ui.trendStatus.textContent = "趋势已更新";
      renderTrend();
      renderTrendSummary();
      setStatus("趋势已更新 · " + payload.run_label + " · 历史回放");
    } catch (error) {
      S.trend = null;
      ui.trendStatus.textContent = "趋势失败";
      ui.trendContext.textContent = "趋势加载失败：" + error.message;
      renderTrend();
      setStatus("趋势加载失败：" + error.message);
    }
  }

  function renderTrend() {
    const { ctx, width, height } = prepareCanvas(ui.trendCanvas);
    renderTrendContext();
    if (!S.trend || !S.trend.points || !S.trend.points.length) {
      ctx.fillStyle = COLORS.text;
      ctx.font = "12px 'Segoe UI', 'Microsoft YaHei', sans-serif";
      ctx.fillText("点击“更新趋势”读取逐帧指标…", 18, 30);
      return;
    }
    const points = S.trend.points;
    const margin = { left: 58, right: 16, top: 24, bottom: 28, gap: 34 };
    const plotW = width - margin.left - margin.right;
    const availableH = height - margin.top - margin.bottom - margin.gap;
    const panelH = availableH / 2;
    const freqTop = margin.top;
    const freqBottom = freqTop + panelH;
    const ampTop = freqBottom + margin.gap;
    const ampBottom = ampTop + panelH;
    const maxT = Math.max(Number(points[points.length - 1].elapsed_s) || 0, 0.001);
    const xOf = (value) => margin.left + plotW * Math.min(1, Math.max(0, Number(value) / maxT));

    const validFrequencies = points.filter((p) => p.valid && Number.isFinite(Number(p.estimated_frequency_hz)))
      .map((p) => Number(p.estimated_frequency_hz));
    let fMin = validFrequencies.length ? Math.min(...validFrequencies) : 0;
    let fMax = validFrequencies.length ? Math.max(...validFrequencies) : 1;
    if (S.trend.mode === "target_band" && S.trend.parameters.target_hz != null) {
      const half = Number(S.trend.parameters.bandwidth_hz || 0) / 2;
      fMin = Math.min(fMin, S.trend.parameters.target_hz - half);
      fMax = Math.max(fMax, S.trend.parameters.target_hz + half);
    }
    const pad = Math.max(10, (fMax - fMin) * 0.12);
    fMin -= pad;
    fMax += pad;
    if (fMax <= fMin) fMax = fMin + 1;

    const validDb = points.filter((p) => p.valid && Number.isFinite(Number(p.dbfs)))
      .map((p) => Number(p.dbfs));
    let aMin = validDb.length ? Math.min(...validDb) : -120;
    let aMax = validDb.length ? Math.max(...validDb) : 0;
    const aPad = Math.max(1, (aMax - aMin) * 0.15);
    aMin -= aPad;
    aMax += aPad;
    if (aMax <= aMin) aMax = aMin + 1;

    const yFreq = (value) => freqBottom - (Math.max(fMin, Math.min(fMax, Number(value))) - fMin) /
      (fMax - fMin) * panelH;
    const yAmp = (value) => ampBottom - (Math.max(aMin, Math.min(aMax, Number(value))) - aMin) /
      (aMax - aMin) * panelH;

    function drawPanelGrid(top, bottom, yValues, formatter) {
      ctx.font = "9px 'Segoe UI', sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      yValues.forEach((value) => {
        const y = top + (bottom - top) * (1 - (value.index || 0));
        ctx.strokeStyle = COLORS.grid;
        ctx.beginPath();
        ctx.moveTo(margin.left, y);
        ctx.lineTo(margin.left + plotW, y);
        ctx.stroke();
        ctx.fillStyle = COLORS.text;
        ctx.fillText(formatter(value.value), margin.left - 7, y);
      });
    }

    ctx.lineWidth = 1;
    drawPanelGrid(freqTop, freqBottom,
      [0, 0.25, 0.5, 0.75, 1].map((index) => ({
        index, value: fMin + (fMax - fMin) * index,
      })), (value) => Number(value).toFixed(1));
    drawPanelGrid(ampTop, ampBottom,
      [0, 0.5, 1].map((index) => ({
        index, value: aMin + (aMax - aMin) * index,
      })), (value) => Number(value).toFixed(1));

    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillStyle = COLORS.text;
    ctx.font = "10px 'Segoe UI', sans-serif";
    ctx.fillText("频率 / Hz", margin.left, freqTop + 4);
    ctx.fillText("峰值 / dBFS", margin.left, ampTop + 4);

    S.trend.events.forEach((event) => {
      const x1 = xOf(event.start_elapsed_s);
      const x2 = xOf(event.end_elapsed_s);
      ctx.fillStyle = event.rule === "amplitude_below"
        ? "rgba(251, 113, 133, 0.12)" : "rgba(251, 191, 36, 0.12)";
      ctx.fillRect(x1, freqTop, Math.max(1, x2 - x1), freqBottom - freqTop);
      ctx.fillRect(x1, ampTop, Math.max(1, x2 - x1), ampBottom - ampTop);
    });

    // Use explicit coordinate mapping for each series; avoids relying on function identity.
    function drawMappedSeries(getter, mapper, color, dash) {
      ctx.beginPath();
      let open = false;
      points.forEach((point) => {
        const value = getter(point);
        if (value === null || value === undefined || !Number.isFinite(Number(value))) {
          open = false;
          return;
        }
        const x = xOf(point.elapsed_s);
        const y = mapper(value);
        if (!open) {
          ctx.moveTo(x, y);
          open = true;
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.4;
      ctx.setLineDash(dash || []);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    drawMappedSeries((p) => p.discrete_frequency_hz, yFreq, "#94a3b8", []);
    drawMappedSeries((p) => p.estimated_frequency_hz, yFreq, "#2563eb", []);
    drawMappedSeries((p) => p.dbfs, yAmp, "#0f766e", []);

    if (S.trend.parameters.threshold_dbfs != null) {
      const threshold = Number(S.trend.parameters.threshold_dbfs);
      const hysteresis = Number(S.trend.parameters.hysteresis_db || 0);
      [threshold, threshold + hysteresis].forEach((value, index) => {
        if (value < aMin || value > aMax) return;
        const y = yAmp(value);
        ctx.strokeStyle = index === 0 ? "#fb7185" : "#fbbf24";
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(margin.left, y);
        ctx.lineTo(margin.left + plotW, y);
        ctx.stroke();
      });
      ctx.setLineDash([]);
    }

    const missingY = S.trend.parameters.target_hz != null ? yFreq(S.trend.parameters.target_hz) : (freqTop + freqBottom) / 2;
    points.forEach((point) => {
      if (!point.valid) {
        const x = xOf(point.elapsed_s);
        ctx.strokeStyle = COLORS.danger;
        ctx.beginPath();
        ctx.moveTo(x - 3, missingY - 3);
        ctx.lineTo(x + 3, missingY + 3);
        ctx.moveTo(x + 3, missingY - 3);
        ctx.lineTo(x - 3, missingY + 3);
        ctx.stroke();
      }
    });

    ctx.fillStyle = COLORS.text;
    ctx.font = "9px 'Segoe UI', sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText("0 s", margin.left, ampBottom + 7);
    ctx.textAlign = "right";
    ctx.fillText(fmtShort(maxT), margin.left + plotW, ampBottom + 7);
    ctx.textAlign = "center";
    ctx.fillText("原始 elapsed_s", margin.left + plotW / 2, ampBottom + 7);
  }

  function renderTrendSummary() {
    if (!S.trend) {
      ui.trendPointCount.textContent = "指标点 —";
      ui.trendValidCount.textContent = "有峰 —";
      ui.trendMissingCount.textContent = "缺测 —";
      ui.trendGapCount.textContent = "断点 —";
      ui.trendEventCount.textContent = "事件 —";
      ui.eventList.innerHTML = '<span class="event-empty">尚无趋势结果</span>';
      return;
    }
    ui.trendPointCount.textContent = "指标点 " + S.trend.point_count;
    ui.trendValidCount.textContent = "有峰 " + S.trend.valid_count;
    ui.trendMissingCount.textContent = "缺测 " + S.trend.missing_count;
    ui.trendGapCount.textContent = "断点 " + S.trend.continuity_gap_count;
    ui.trendEventCount.textContent = "事件 " + S.trend.event_count;
    ui.eventList.innerHTML = "";
    if (!S.trend.events.length) {
      const empty = document.createElement("span");
      empty.className = "event-empty";
      empty.textContent = "当前参数未触发事件";
      ui.eventList.appendChild(empty);
      return;
    }
    S.trend.events.forEach((event) => {
      const chip = document.createElement("span");
      chip.className = "event-chip";
      chip.textContent = event.rule + " · frame " + event.start_frame_id + "–" +
        event.end_frame_id + " · " + fmtShort(event.start_elapsed_s) + "–" +
        fmtShort(event.end_elapsed_s);
      chip.title = event.reason;
      ui.eventList.appendChild(chip);
    });
  }

  async function exportAnalysis() {
    if (!S.run || !S.frame) {
      ui.exportResult.textContent = "请先加载一份完整频谱";
      return;
    }
    let trend;
    try {
      trend = trendParams();
    } catch (error) {
      ui.exportResult.textContent = "导出参数错误：" + error.message;
      return;
    }
    const observed = S.feature.frames.length
      ? S.feature.frames.map((item) => item.frame_id)
      : [S.frame.frame_id];
    const payload = {
      run_id: S.run.run_id,
      observed_frame_ids: observed,
      current_frame_id: S.frame.frame_id,
      average_length: S.averageLength,
      cursor_curve: S.cursorCurve,
      cursors: S.cursors,
      trend: Object.assign({}, trend, { run_id: S.run.run_id }),
    };
    if (DATA_SOURCE === "user") payload.record_id = RECORD_ID;
    ui.exportBtn.disabled = true;
    ui.exportResult.textContent = "正在生成可重算分析包…";
    try {
      const result = await fetchJSON("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      ui.exportResult.textContent = "已导出：" + result.package_path +
        " · 平均 " + result.summary.average.count +
        " 份 · 保持 " + result.summary.hold.count +
        " 份 · 事件 " + result.summary.trend.event_count;
      setStatus("分析包已导出（" + sourceLabel() + "）");
    } catch (error) {
      ui.exportResult.textContent = "导出失败：" + error.message;
      setStatus("导出失败：" + error.message);
    } finally {
      ui.exportBtn.disabled = false;
    }
  }

  function renderSpectrum() {
    const { ctx, width, height } = prepareCanvas(ui.spectrumCanvas);
    if (!S.frame) {
      ctx.fillStyle = COLORS.text;
      ctx.font = "13px 'Segoe UI', 'Microsoft YaHei', sans-serif";
      ctx.fillText("等待完整频谱留样…", 20, 32);
      return;
    }

    const margin = { left: 56, right: 14, top: 14, bottom: 28 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const bottom = margin.top + plotH;
    const maxIndex = maxIndexForRange(S.frame.frequency_hz, S.rangeHz);
    const dbMin = -120;
    const dbMax = 0;

    S.plotBounds = { left: margin.left, right: margin.left + plotW, top: margin.top, bottom, maxIndex };
    const xOf = (index) => margin.left + plotW * (index / Math.max(1, maxIndex));
    const yOf = (db) => margin.top + (dbMax - Math.max(dbMin, Math.min(dbMax, Number(db)))) /
      (dbMax - dbMin) * plotH;

    ctx.lineWidth = 1;
    ctx.font = "10px 'Segoe UI', sans-serif";
    ctx.fillStyle = COLORS.text;
    ctx.strokeStyle = COLORS.grid;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let db = dbMin; db <= dbMax; db += 30) {
      const y = margin.top + (dbMax - db) / (dbMax - dbMin) * plotH;
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(margin.left + plotW, y);
      ctx.stroke();
      ctx.fillText(db + " dB", margin.left - 8, y);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let i = 0; i <= 4; i += 1) {
      const x = margin.left + plotW * i / 4;
      const hz = S.rangeHz * i / 4;
      ctx.strokeStyle = i === 0 ? COLORS.gridStrong : COLORS.grid;
      ctx.beginPath();
      ctx.moveTo(x, margin.top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillText(fmtHz(hz), x, bottom + 7);
    }

    function pointsFor(values) {
      const points = [];
      for (let i = 0; i <= maxIndex; i += 1) {
        points.push([xOf(i), yOf(values[i])]);
      }
      return points;
    }

    function drawCurve(values, color, lineWidth, dash, fill) {
      const points = pointsFor(values);
      if (!points.length) return points;
      if (fill) {
        const gradient = ctx.createLinearGradient(0, margin.top, 0, bottom);
        gradient.addColorStop(0, "rgba(94, 234, 212, 0.25)");
        gradient.addColorStop(1, "rgba(94, 234, 212, 0.015)");
        ctx.beginPath();
        ctx.moveTo(points[0][0], bottom);
        points.forEach(([x, y]) => ctx.lineTo(x, y));
        ctx.lineTo(points[points.length - 1][0], bottom);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();
      }
      ctx.beginPath();
      points.forEach(([x, y], index) => {
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.setLineDash(dash || []);
      ctx.stroke();
      ctx.setLineDash([]);
      return points;
    }

    let peakIndex = 0;
    let peakRaw = -Infinity;
    for (let i = 0; i <= maxIndex; i += 1) {
      const raw = Number(S.frame.dbfs[i]);
      if (raw > peakRaw) {
        peakRaw = raw;
        peakIndex = i;
      }
    }

    const averageDbfs = S.feature.average ? dbFromLinear(S.feature.average) : null;
    const holdDbfs = S.feature.hold ? dbFromLinear(S.feature.hold) : null;
    if (S.showCurrent) {
      drawCurve(S.frame.dbfs, COLORS.accent, 1.6, [], true);
    }
    if (S.showAverage && averageDbfs) {
      drawCurve(averageDbfs, "#60a5fa", 1.8, [], false);
    }
    if (S.showHold && holdDbfs) {
      drawCurve(holdDbfs, COLORS.amber, 1.6, [5, 4], false);
    }

    if (S.showCurrent) {
      const peakX = xOf(peakIndex);
      const peakY = yOf(peakRaw);
      ctx.beginPath();
      ctx.arc(peakX, peakY, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.amber;
      ctx.fill();
      ui.peakReadout.textContent = fmtHz(S.frame.frequency_hz[peakIndex]) + " / " + fmtDb(peakRaw);
    } else {
      ui.peakReadout.textContent = "当前谱已隐藏";
    }

    const selectedCurve = cursorCurveData();
    ["A", "B"].forEach((key) => {
      const bin = S.cursors[key];
      if (bin === null || bin === undefined) return;
      const color = key === "A" ? COLORS.amber : "#c084fc";
      if (bin > maxIndex) {
        ctx.fillStyle = color;
        ctx.font = "10px 'Segoe UI', sans-serif";
        ctx.textAlign = "right";
        ctx.textBaseline = "top";
        ctx.fillText(key + " 在显示范围外", margin.left + plotW - 4, margin.top + (key === "A" ? 4 : 18));
        return;
      }
      const cursorX = xOf(bin);
      ctx.strokeStyle = color;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(cursorX, margin.top);
      ctx.lineTo(cursorX, bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "bold 10px 'Segoe UI', sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(key, cursorX + 3, margin.top + (key === "A" ? 3 : 16));
      const selectedVisible =
        (S.cursorCurve === "current" && S.showCurrent) ||
        (S.cursorCurve === "average" && S.showAverage) ||
        (S.cursorCurve === "hold" && S.showHold);
      if (selectedCurve && selectedVisible) {
        ctx.beginPath();
        ctx.arc(cursorX, yOf(selectedCurve.dbfs[bin]), 3.2, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      }
    });
    updateCursorReadings();
  }

  function renderWaterfall() {
    const { ctx, width, height } = prepareCanvas(ui.waterfallCanvas);
    const rows = Array.from(S.waterfall.values()).sort((a, b) => a.frame_id - b.frame_id);
    const margin = { left: 104, right: 10, top: 30, bottom: 22 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;

    ctx.font = "11px 'Segoe UI', 'Microsoft YaHei', sans-serif";
    ctx.fillStyle = COLORS.text;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText("留样序号 / 原始时间", 10, 14);
    ctx.textAlign = "right";
    ctx.fillText("频率 →", width - 10, 14);

    if (!rows.length) {
      ctx.textAlign = "center";
      ctx.fillStyle = COLORS.text;
      ctx.fillText("尚无留样；播放或点击“查看”后显示", width / 2, height / 2);
      return;
    }

    const rowH = Math.min(34, Math.max(14, plotH / rows.length));
    const maxIndex = Math.max(1, maxIndexForRange(rows[0].frequency_hz, S.rangeHz));
    rows.forEach((row, rowIndex) => {
      const top = margin.top + rowIndex * rowH;
      if (top + rowH > margin.top + plotH + 4) return;
      const label = "#" + String(row.sample_index).padStart(2, "0") + "  " + fmtShort(row.elapsed_s);
      ctx.fillStyle = row.frame_id === S.frame?.frame_id ? COLORS.accent : COLORS.text;
      ctx.textAlign = "left";
      ctx.fillText(label, 8, top + rowH / 2);

      for (let i = 0; i <= maxIndex; i += 1) {
        const x = margin.left + plotW * i / Math.max(1, maxIndex);
        const w = Math.max(1, plotW / Math.max(1, maxIndex) + 0.3);
        ctx.fillStyle = colorForDb(row.dbfs[i]);
        ctx.fillRect(x, top + 1, w, Math.max(1, rowH - 2));
      }
      if (row.frame_id === S.frame?.frame_id) {
        ctx.strokeStyle = COLORS.accent;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(margin.left, top + 1, plotW, Math.max(1, rowH - 2));
      }
    });

    ctx.strokeStyle = COLORS.gridStrong;
    ctx.lineWidth = 1;
    ctx.strokeRect(margin.left, margin.top, plotW, Math.min(plotH, rows.length * rowH));
    ctx.fillStyle = COLORS.text;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText("稀疏留样：每行一个 frame_id，不是连续音频", margin.left + plotW / 2, height - 16);
  }

  function renderTimeline() {
    const { ctx, width, height } = prepareCanvas(ui.timelineCanvas);
    if (!S.run || !S.samples.length) {
      ctx.fillStyle = COLORS.text;
      ctx.font = "12px 'Segoe UI', 'Microsoft YaHei', sans-serif";
      ctx.fillText("请选择一条实验记录", 16, 28);
      return;
    }
    const margin = { left: 22, right: 22, top: 30, bottom: 22 };
    const plotW = width - margin.left - margin.right;
    const y = margin.top + (height - margin.top - margin.bottom) / 2;
    const maxTime = Math.max(
      Number(S.run.summary_elapsed_s || 0),
      Number(S.run.last_elapsed_s || 0),
      Number(S.samples[S.samples.length - 1].elapsed_s || 0),
      0.001
    );
    const xOf = (time) => margin.left + plotW * Math.min(1, Math.max(0, Number(time) / maxTime));

    ctx.strokeStyle = COLORS.gridStrong;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(margin.left + plotW, y);
    ctx.stroke();

    S.run.segments.forEach((segment) => {
      const x1 = xOf(segment.from_elapsed_s);
      const x2 = xOf(segment.to_elapsed_s);
      ctx.fillStyle = "rgba(251, 191, 36, 0.08)";
      ctx.fillRect(x1, y - 12, Math.max(1, x2 - x1), 24);
      if (x2 - x1 > 34 && segment.metric_rows_between > 0) {
        ctx.fillStyle = COLORS.amber;
        ctx.font = "9px 'Segoe UI', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(segment.metric_rows_between + " 条指标", (x1 + x2) / 2, y - 17);
      }
    });

    S.samples.forEach((sample, index) => {
      const x = xOf(sample.elapsed_s);
      const current = S.currentIdx === index;
      ctx.beginPath();
      ctx.arc(x, y, current ? 6 : 4, 0, Math.PI * 2);
      ctx.fillStyle = current ? COLORS.accent : COLORS.amber;
      ctx.fill();
      if (current) {
        ctx.strokeStyle = COLORS.accent;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, y, 10, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.fillStyle = COLORS.text;
      ctx.font = "9px 'Segoe UI', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText("#" + (index + 1), x, y + 12);
    });

    ctx.fillStyle = COLORS.text;
    ctx.font = "10px 'Segoe UI', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("0 s", margin.left, height - 15);
    ctx.textAlign = "right";
    ctx.fillText(fmtShort(maxTime), margin.left + plotW, height - 15);
  }

  function renderMeta() {
    const frame = S.frame;
    const run = S.run;
    ui.runName.textContent = run ? (run.label + " · " + run.window) : "—";
    ui.frameText.textContent = frame ? String(frame.frame_id) : "—";
    ui.sampleIndexText.textContent = frame ? (frame.sample_index + " / " + (run ? run.samples.length : 0)) : "—";
    ui.sequenceText.textContent = frame ? String(frame.sequence) : "—";
    ui.elapsedText.textContent = frame ? fmtTime(frame.elapsed_s) : "—";
    ui.windowText.textContent = frame ? frame.window : "—";
    ui.fsText.textContent = frame ? fmtHz(frame.fs_hz) : "—";
    ui.sourceBadge.textContent = sourceLabel();
    ui.runMetricRows.textContent = run ? String(run.metric_rows) : "—";
    ui.runSavedSamples.textContent = run ? String(run.saved_samples) : "—";
    ui.shownSamples.textContent = String(S.stats.shown);
    ui.uniqueSamples.textContent = String(S.waterfall.size);
  }

  function renderGap(index) {
    if (!S.run || index <= 0 || index >= S.samples.length) {
      ui.gapTitle.textContent = "起点留样";
      ui.gapDetail.textContent = index === 0
        ? "当前为第 1 份完整频谱；此前没有可播放留样。"
        : "当前没有可显示的相邻留样。";
      ui.gapWait.textContent = "";
      return;
    }
    const previous = S.samples[index - 1];
    const current = S.samples[index];
    const segment = S.run.segments.find((item) => item.to_frame_id === current.frame_id);
    ui.gapTitle.textContent = "该区间未留存完整频谱";
    if (segment) {
      ui.gapDetail.textContent =
        "frame " + previous.frame_id + " (" + fmtShort(previous.elapsed_s) + ") → frame " +
        current.frame_id + " (" + fmtShort(current.elapsed_s) + ")；中间 " +
        segment.metric_rows_between + " 条逐帧指标没有完整频谱，当前只播放留样 " +
        current.frame_id + "。";
    } else {
      ui.gapDetail.textContent = "相邻留样之间没有完整频谱，当前不插造中间曲线。";
    }
  }

  function renderSampleTable() {
    if (!S.run) {
      ui.sampleTableBody.innerHTML = '<tr><td colspan="8" class="empty">请选择一条实验记录</td></tr>';
      return;
    }
    ui.sampleTableBody.innerHTML = "";
    S.samples.forEach((sample, index) => {
      const tr = document.createElement("tr");
      if (index === S.currentIdx) tr.className = "current";
      tr.innerHTML =
        "<td>" + (index + 1) + "</td>" +
        "<td>" + sample.frame_id + "</td>" +
        "<td>" + sample.sequence + "</td>" +
        "<td>" + fmtTime(sample.elapsed_s) + "</td>" +
        "<td>" + fmtHz(sample.peak_hz) + "</td>" +
        "<td>" + fmtDb(sample.peak_dbfs) + "</td>" +
        "<td>" + (sample.tone_checks_passed === true ? "通过" : "—") + "</td>" +
        '<td><button class="row-button" data-index="' + index + '" type="button">查看</button></td>';
      ui.sampleTableBody.appendChild(tr);
    });
  }

  function renderAll() {
    renderSpectrum();
    renderWaterfall();
    renderTimeline();
    renderMeta();
    renderFeatureStats();
    renderTrendContext();
    if (S.currentIdx >= 0) renderGap(S.currentIdx);
    renderSampleTable();
    updateControls();
  }

  async function showSample(index, options) {
    if (!S.run || index < 0 || index >= S.samples.length) return false;
    const opts = options || {};
    const token = ++S.requestToken;
    const sample = S.samples[index];
    setStatus("读取留样 frame " + sample.frame_id + " …");
    try {
      const frame = await fetchJSON(
        "/api/replay/frame?run_id=" + encodeURIComponent(S.run.run_id) +
        "&frame_id=" + encodeURIComponent(sample.frame_id)
      );
      if (token !== S.requestToken) return false;
      S.frame = frame;
      S.currentIdx = index;
      if (!S.cursorLocked) S.cursors = { A: null, B: null };
      updateFeatures(frame);
      if (!S.waterfall.has(sample.frame_id)) {
        S.stats.shown += 1;
        S.stats.firstElapsed = S.stats.firstElapsed === null ? sample.elapsed_s : S.stats.firstElapsed;
        S.stats.lastElapsed = sample.elapsed_s;
      }
      S.waterfall.set(sample.frame_id, Object.assign({}, sample, {
        dbfs: frame.dbfs,
        frequency_hz: frame.frequency_hz,
      }));
      renderAll();
      setStatus(sourceLabel() + " · frame " + sample.frame_id + " · 原始 " + fmtTime(sample.elapsed_s));
      return true;
    } catch (error) {
      if (token === S.requestToken) {
        pause("加载失败：" + error.message);
        ui.gapTitle.textContent = "该 frame 未留存完整频谱";
        ui.gapDetail.textContent = error.message;
      }
      return false;
    }
  }

  function segmentForNext() {
    if (!S.run || S.currentIdx < 0 || S.currentIdx >= S.samples.length - 1) return null;
    const next = S.samples[S.currentIdx + 1];
    return S.run.segments.find((item) => item.to_frame_id === next.frame_id) || null;
  }

  function scheduleNext() {
    clearTimer();
    if (!S.playing) return;
    if (S.currentIdx >= S.samples.length - 1) {
      endPlayback();
      return;
    }
    const previous = S.samples[S.currentIdx];
    const next = S.samples[S.currentIdx + 1];
    const gap = Math.max(0, Number(next.elapsed_s) - Number(previous.elapsed_s));
    const delay = S.mode === "original"
      ? Math.max(180, gap * 1000 / S.speed)
      : Math.max(180, 1000 / S.speed);
    const segment = segmentForNext();
    ui.gapWait.textContent = S.mode === "original"
      ? "等待原始间隔 " + fmtShort(gap) + " ÷ " + S.speed + "× = " + fmtShort(delay / 1000) +
        "；中间 " + (segment ? segment.metric_rows_between : 0) + " 条指标无完整频谱。"
      : "等间隔浏览：下一份将在 " + fmtShort(delay / 1000) + " 后显示；原始间隔 " +
        fmtShort(gap) + " 仅作标签。";
    setStatus(S.mode === "original"
      ? "播放中 · 按原始时间槽（" + S.speed + "×）"
      : "播放中 · 等间隔浏览留样（" + S.speed + "×）");
    S.timer = setTimeout(async () => {
      if (!S.playing) return;
      const ok = await showSample(S.currentIdx + 1, { append: true });
      if (ok && S.playing) scheduleNext();
      else if (!ok && S.playing) pause("加载失败，已暂停");
    }, delay);
  }

  function endPlayback() {
    S.playing = false;
    clearTimer();
    updateControls();
    setStatus("播放结束 · 未自动循环");
    ui.gapWait.textContent = "播放结束：如需再次播放，请点击“重新播放”；新一轮不会重复累计旧统计。";
  }

  async function play() {
    if (!S.samples.length) return;
    if (S.currentIdx >= S.samples.length - 1) {
      resetPass();
      setStatus("重新播放：已清空上一轮瀑布、统计、曲线和游标");
      const ok = await showSample(0, { append: true });
      if (!ok) return;
    }
    S.playing = true;
    updateControls();
    scheduleNext();
  }

  async function step(delta) {
    const next = S.currentIdx + delta;
    pause("");
    if (next < 0) {
      setStatus("已经是最前一份");
      return;
    }
    if (next >= S.samples.length) {
      setStatus("已经是最后一份");
      return;
    }
    await showSample(next, { append: true });
    if (S.frame) setStatus("手动切换 · 留样 #" + (next + 1) + " / frame " + S.frame.frame_id);
  }

  async function selectRun(runId) {
    pause("");
    const run = S.runs.find((item) => item.run_id === runId);
    if (!run) {
      setStatus("未知实验记录：" + runId);
      return;
    }
    S.run = run;
    S.samples = run.samples;
    S.currentIdx = -1;
    S.frame = null;
    S.waterfall.clear();
    S.stats = { shown: 0, firstElapsed: null, lastElapsed: null };
    resetCursors("");
    ui.gapWait.textContent = "";
    resetFeatures("切换实验记录 / 窗口");
    renderGap(-1);
    renderAll();
    setStatus("已加载实验记录：" + run.label + "；瀑布、统计、曲线、游标已清空");
    if (run.samples.length) {
      await showSample(0, { append: true });
      await loadTrend();
      if (S.frame) setStatus(sourceLabel() + " · " + run.label + " · 起点留样 #1");
    }
  }

  function showEmptyState() {
    pause("");
    S.run = null;
    S.samples = [];
    S.currentIdx = -1;
    S.frame = null;
    S.waterfall.clear();
    S.stats = { shown: 0, firstElapsed: null, lastElapsed: null };
    S.trend = null;
    resetCursors("");
    resetFeatures("尚未选择实验记录");
    ui.trendStatus.textContent = "趋势未加载";
    ui.trendContext.textContent = "选择一条实验记录后，可查看趋势和完整频谱样例。";
    ui.eventList.replaceChildren();
    ui.exportResult.textContent = "";
    ui.gapTitle.textContent = "尚未加载历史样例";
    ui.gapDetail.textContent = "实验数据仅在用户主动选择后显示。";
    ui.gapWait.textContent = "";
    renderAll();
    setStatus("请选择一条实验记录以加载历史样例");
  }

  async function loadDualCursorDemo(curve) {
    const run = S.runs.find((item) => item.run_id === "spectrum_38749b56cab6") ||
      S.runs.find((item) => item.label === "dual_hann") ||
      S.runs.find((item) => item.label === "dual_rect");
    if (!run) {
      setStatus("样例索引中没有双音实验记录");
      return;
    }
    ui.runSelect.value = run.run_id;
    await selectRun(run.run_id);
    if (!S.frame) return;
    S.cursorCurve = (curve === "average" || curve === "hold") ? curve : "current";
    ui.cursorCurveSelect.value = S.cursorCurve;
    S.cursors.A = nearestBin(S.frame.frequency_hz, 1000);
    S.cursors.B = nearestBin(S.frame.frequency_hz, 3000);
    S.activeCursor = "A";
    S.cursorLocked = true;
    ui.cursorToggle.checked = true;
    updateCursorButtons();
    renderAll();
    updateCursorReadings();
    const fa = S.frame.frequency_hz[S.cursors.A];
    const fb = S.frame.frequency_hz[S.cursors.B];
    setStatus("双音 A/B 示例：bin " + S.cursors.A + " / " + S.cursors.B +
      " · " + fmtHz(fa) + " / " + fmtHz(fb) + "（真实 FFT bin）");
  }

  function bindEvents() {
    ui.runSelect.addEventListener("change", () => {
      if (!ui.runSelect.value) {
        showEmptyState();
        return;
      }
      selectRun(ui.runSelect.value).catch((error) => setStatus("加载实验记录失败：" + error.message));
    });
    ui.modeSelect.addEventListener("change", () => {
      S.mode = ui.modeSelect.value;
      setModeHint();
      if (S.playing) scheduleNext();
    });
    ui.speedSelect.addEventListener("change", () => {
      S.speed = Number(ui.speedSelect.value) || 1;
      if (S.playing) scheduleNext();
    });
    ui.rangeSelect.addEventListener("change", () => {
      S.rangeHz = Number(ui.rangeSelect.value) || 24000;
      renderSpectrum();
      renderWaterfall();
      renderTimeline();
      updateControls();
    });
    ui.playBtn.addEventListener("click", () => {
      if (S.playing) pause("已暂停 · 当前留样序号不变");
      else play().catch((error) => pause("播放失败：" + error.message));
    });
    ui.prevBtn.addEventListener("click", () => {
      step(-1).catch((error) => setStatus("切换失败：" + error.message));
    });
    ui.nextBtn.addEventListener("click", () => {
      step(1).catch((error) => setStatus("切换失败：" + error.message));
    });
    ui.sampleTableBody.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-index]");
      if (!button) return;
      pause("");
      showSample(Number(button.dataset.index), { append: true }).catch((error) => {
        setStatus("加载失败：" + error.message);
      });
    });
    ui.cursorToggle.addEventListener("change", () => {
      S.cursorLocked = ui.cursorToggle.checked;
      setStatus(S.cursorLocked ? "游标已锁定：跨帧保持" : "游标已解锁：下一帧清除");
    });
    ui.cursorCurveSelect.addEventListener("change", () => {
      S.cursorCurve = ui.cursorCurveSelect.value;
      renderSpectrum();
      updateCursorReadings();
      setStatus("测量对象切换为：" + ({
        current: "当前谱",
        average: "均方幅度平均谱",
        hold: "峰值保持",
      })[S.cursorCurve]);
    });
    ui.cursorABtn.addEventListener("click", () => {
      S.activeCursor = "A";
      updateCursorButtons();
      setStatus("活动游标 A：点击频谱移动");
    });
    ui.cursorBBtn.addEventListener("click", () => {
      S.activeCursor = "B";
      updateCursorButtons();
      setStatus("活动游标 B：点击频谱移动");
    });
    ui.dualDemoBtn.addEventListener("click", () => {
      loadDualCursorDemo().catch((error) => setStatus("双音游标示例失败：" + error.message));
    });
    ui.averageLengthSelect.addEventListener("change", () => {
      S.averageLength = Number(ui.averageLengthSelect.value) === 32 ? 32 : 8;
      updateFeatureAverage();
      renderFeatureStats();
      renderSpectrum();
      setStatus("平均长度已改为 " + S.averageLength + " 份；保持曲线不重置");
    });
    ui.showCurrent.addEventListener("change", () => {
      S.showCurrent = ui.showCurrent.checked;
      renderSpectrum();
    });
    ui.showAverage.addEventListener("change", () => {
      S.showAverage = ui.showAverage.checked;
      renderSpectrum();
    });
    ui.showHold.addEventListener("change", () => {
      S.showHold = ui.showHold.checked;
      renderSpectrum();
    });
    ui.clearFeaturesBtn.addEventListener("click", () => {
      resetFeatures("手动清空");
      setStatus("已清空均方幅度平均谱和峰值保持；当前留样仍保留");
    });
    ui.trendMode.addEventListener("change", () => {
      updateTrendModeControls();
      setStatus("趋势选择已切换；点击“更新趋势”重新计算");
    });
    ui.trendApplyBtn.addEventListener("click", () => {
      loadTrend().catch((error) => setStatus("趋势更新失败：" + error.message));
    });
    ui.exportBtn.addEventListener("click", () => {
      exportAnalysis().catch((error) => {
        ui.exportResult.textContent = "导出失败：" + error.message;
        setStatus("导出失败：" + error.message);
      });
    });
    ui.spectrumCanvas.addEventListener("click", (event) => {
      if (!S.frame || !S.plotBounds) return;
      const rect = ui.spectrumCanvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const bounds = S.plotBounds;
      if (x < bounds.left || x > bounds.right) return;
      const fraction = (x - bounds.left) / Math.max(1, bounds.right - bounds.left);
      S.cursors[S.activeCursor] = Math.min(bounds.maxIndex, Math.max(0, Math.round(fraction * bounds.maxIndex)));
      renderSpectrum();
      updateCursorReadings();
    });
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        renderSpectrum();
        renderWaterfall();
        renderTimeline();
      }, 80);
    });
  }

  async function boot() {
    setStatus(DATA_SOURCE === "user" ? "正在读取用户记录…" : "正在读取样例索引…");
    const index = await fetchJSON("/api/replay/index");
    S.index = index;
    S.runs = index.runs || [];
    if (!S.runs.length) throw new Error("样例索引中没有实验记录");

    fillSelect(ui.modeSelect, index.playback_modes || [], (item) => item.id, (item) => item.label);
    fillSelect(ui.speedSelect, (index.speed_options || [1, 2, 5, 10, 20, 50]).map((value) => ({ value })),
      (item) => String(item.value), (item) => item.value + "×");
    fillSelect(ui.runSelect, S.runs, (run) => run.run_id,
      (run) => run.label + " · " + run.window + " · " + run.metric_rows + " 条指标 / " + run.saved_samples + " 份留样");
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "请选择实验记录（可选）";
    ui.runSelect.prepend(placeholder);
    ui.runSelect.value = "";
    ui.modeSelect.value = "original";
    ui.speedSelect.value = "20";
    S.mode = "original";
    S.speed = 20;
    setModeHint();
    updateTrendModeControls();
    ui.runSelect.disabled = false;
    bindEvents();

    const params = new URLSearchParams(window.location.search);
    const requestedAverage = Number(params.get("avg"));
    if (requestedAverage === 32 || requestedAverage === 8) {
      S.averageLength = requestedAverage;
      ui.averageLengthSelect.value = String(requestedAverage);
    }
    const requestedRange = Number(params.get("range"));
    if (requestedRange === 5000 || requestedRange === 12000 || requestedRange === 24000) {
      S.rangeHz = requestedRange;
      ui.rangeSelect.value = String(requestedRange);
    }
    const requestedCurve = params.get("curve");
    if (requestedCurve === "current" || requestedCurve === "average" || requestedCurve === "hold") {
      S.cursorCurve = requestedCurve;
      ui.cursorCurveSelect.value = requestedCurve;
    }
    const requestedDemo = params.has("demo");
    const requestedExport = params.get("export") === "1";
    const requestedUserRecord = DATA_SOURCE === "user" && Boolean(RECORD_ID);
    const preferred = S.runs.find((run) => run.label === "long_hann_tone1k") || S.runs[0];
    if (requestedDemo || requestedExport || requestedUserRecord) {
      ui.runSelect.value = preferred.run_id;
      await selectRun(preferred.run_id);
    } else {
      showEmptyState();
    }
    if (params.get("demo") === "bx07") {
      await loadDualCursorDemo(requestedCurve);
      ui.trendMode.value = "target_band";
      updateTrendModeControls();
      ui.trendTarget.value = "1000";
      ui.trendBandwidth.value = "200";
      await loadTrend();
    } else if (params.get("demo") === "bx05") {
      await loadDualCursorDemo(requestedCurve);
    } else if (params.get("demo") === "pause") {
      await step(1);
      pause("已暂停 · 当前留样序号不变");
    } else if (params.get("demo") === "1") {
      ui.modeSelect.value = "equal";
      S.mode = "equal";
      ui.speedSelect.value = "50";
      S.speed = 50;
      setModeHint();
      await play();
    }
    if (params.get("export") === "1") {
      await exportAnalysis();
    }
  }

  boot().catch((error) => {
    setStatus("回放工作台加载失败：" + error.message);
    ui.gapTitle.textContent = "回放索引不可用";
    ui.gapDetail.textContent = error.message;
    ui.playBtn.disabled = true;
    ui.prevBtn.disabled = true;
    ui.nextBtn.disabled = true;
  });
})();
