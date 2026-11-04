(() => {
  "use strict";

  const token = document.querySelector('meta[name="control-token"]').content;
  const panels = {
    spectrum: document.getElementById("panel-spectrum"),
    analysis: document.getElementById("panel-analysis"),
    records: document.getElementById("panel-records"),
    demo: document.getElementById("panel-bplus"),
    m4: document.getElementById("panel-m4"),
  };
  const tabs = Array.from(document.querySelectorAll(".workspace-tab"));
  const frame = document.getElementById("bplusFrame");
  const exportButton = document.getElementById("exportButton");
  const hardwareText = document.getElementById("hardwareModeText");
  const analysisLiveText = document.getElementById("analysisLiveText");
  const analysisSaveResult = document.getElementById("analysisSaveResult");
  const analysisRecordStatus = document.getElementById("analysisRecordStatus");
  const startAnalysisRecordButton = document.getElementById("startAnalysisRecordButton");
  const stopAnalysisRecordButton = document.getElementById("stopAnalysisRecordButton");
  const discardAnalysisRecordButton = document.getElementById("discardAnalysisRecordButton");
  const saveAnalysisButton = document.getElementById("saveAnalysisButton");
  const analysisFrameLimit = document.getElementById("analysisFrameLimit");
  const recordViewerFrame = document.getElementById("recordViewerFrame");
  const m4Result = document.getElementById("m4ResultText");
  const responseSaveResult = document.getElementById("responseSaveResult");
  const responseRecordStatus = document.getElementById("responseRecordStatus");
  const startResponseRecordButton = document.getElementById("startResponseRecordButton");
  const stopResponseRecordButton = document.getElementById("stopResponseRecordButton");
  const discardResponseRecordButton = document.getElementById("discardResponseRecordButton");
  const captureResponsePointButton = document.getElementById("captureResponsePointButton");
  const responseProfileSelect = document.getElementById("responseProfileSelect");
  const responseRcFields = document.getElementById("responseRcFields");
  const responseGenericFields = document.getElementById("responseGenericFields");
  const recordsList = document.getElementById("recordsList");
  const recordDetailText = document.getElementById("recordDetailText");
  const deleteRecordButton = document.getElementById("deleteRecordButton");
  const responseRecordViewer = document.getElementById("responseRecordViewer");
  const responseRecordImage = document.getElementById("responseRecordImage");
  const responseRecordTable = document.getElementById("responseRecordTable");
  const downloadResponseCsv = document.getElementById("downloadResponseCsv");
  const downloadResponseJson = document.getElementById("downloadResponseJson");
  const inputLabel = document.getElementById("m4CaptureLabel");
  let activePanel = "spectrum";
  let hardwareBusy = false;
  let currentHardwareMode = null;
  let currentRecordId = null;
  const responseProfile = () => responseProfileSelect.value === "generic"
    ? "generic" : "rc";

  async function request(path, payload) {
    const options = payload === undefined
      ? { cache: "no-store" }
      : {
          method: "POST",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json",
            "X-Spectrum-Token": token,
          },
          body: JSON.stringify(payload),
        };
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
    return data;
  }

  function setHardwareBusy(value) {
    hardwareBusy = value;
    if (value) {
      for (const button of document.querySelectorAll("#panel-m4 button")) {
        button.disabled = true;
      }
    }
  }

  function selectPanel(name) {
    activePanel = name;
    for (const tab of tabs) {
      tab.classList.toggle("active", tab.dataset.panel === name);
    }
    for (const [key, panel] of Object.entries(panels)) {
      panel.hidden = key !== name;
      panel.classList.toggle("active", key === name);
    }
    exportButton.style.visibility = name === "spectrum" ? "visible" : "hidden";
    if (name === "demo" && !frame.src) frame.src = frame.dataset.src;
    if (name === "analysis") refreshLiveAnalysis();
    if (name === "records") refreshRecords();
    if (name === "m4") refreshHardware();
  }

  async function command(path, payload, resultElement, successText) {
    if (hardwareBusy) return;
    setHardwareBusy(true);
    if (resultElement) resultElement.textContent = "操作中…";
    try {
      const result = await request(path, payload || {});
      if (resultElement) {
        const details = [];
        if (result.label) details.push("记录：" + result.label);
        if (result.fs_hz) details.push("采样率：" + Number(result.fs_hz).toFixed(2) + " Hz");
        if (result.shape) details.push("数据形状：" + result.shape.join(" × "));
        if (result.channel_rms) {
          details.push("左/右 RMS：" + result.channel_rms.map(
            (value) => Number(value).toFixed(6)).join(" / "));
        }
        resultElement.textContent = successText +
          (details.length ? "\n" + details.join("\n") : "");
      }
      await refreshHardware();
      return result;
    } catch (error) {
      if (resultElement) resultElement.textContent = "操作失败：" + error.message;
      return null;
    } finally {
      setHardwareBusy(false);
      await refreshHardware();
    }
  }

  function phaseLabel(mode, phase) {
    if (mode === "M4") return "电路测量";
    if (mode === "FAULT") return "硬件异常";
    return {
      IDLE: "已停止",
      CONFIGURING: "正在配置",
      RUNNING: "正在采集",
      ERROR: "异常停止",
    }[phase] || phase || "未知";
  }

  async function refreshHardware() {
    try {
      const result = await request("/bx/api/hardware/status");
      currentHardwareMode = result.mode;
      const measurement = result.m4;
      const ready = result.mode === "M4" && measurement && measurement.codec_ready;
      const lines = [
        "当前模式：" + ({
          FFT: "实时频谱",
          M4: "电路测量",
          FAULT: "硬件异常",
        }[result.mode] || result.mode || "未知"),
      ];
      if (result.mode === "FFT" && result.fft) {
        lines.push("频谱状态：" + phaseLabel("FFT", result.fft.phase));
      }
      if (result.mode === "M4" && measurement) {
        lines.push("接口配置：" + (measurement.codec_ready ? "已完成" : "未完成"));
        lines.push("采样率：" + (measurement.fs_hz
          ? Number(measurement.fs_hz).toFixed(2) + " Hz" : "未测量"));
        lines.push("已采集：" + (measurement.capture_count || 0) + " 份");
        if (measurement.last_capture) {
          lines.push("最近记录：" + measurement.last_capture.label);
        }
      }
      if (result.fault) lines.push("故障：请保留日志并重启服务或板卡");
      hardwareText.textContent = lines.join("\n");
      document.getElementById("configureM4Button").disabled =
        hardwareBusy || result.mode !== "M4";
      document.getElementById("selfTestM4Button").disabled =
        hardwareBusy || result.mode !== "M4";
      document.getElementById("captureM4Button").disabled =
        hardwareBusy || !ready;
      document.getElementById("enterM4Button").disabled =
        hardwareBusy || result.mode !== "FFT";
      document.getElementById("restoreFftButton").disabled =
        hardwareBusy || result.mode === "FFT";
      document.getElementById("saveResponseButton").disabled = true;
      await refreshResponseRecord();
    } catch (error) {
      hardwareText.textContent = "硬件状态读取失败：" + error.message;
    }
  }

  async function refreshResponseRecord() {
    try {
      const profile = responseProfile();
      const response = await request(
        "/bx/api/response/record/status?profile=" + encodeURIComponent(profile));
      const status = response.status;
      responseRecordStatus.textContent = [
        "测量类型：" + (profile === "rc" ? "RC 低通滤波器" : "通用系统"),
        "记录状态：" + (status.active ? "正在记录" : "未在记录"),
        "已采集频点：" + (status.point_count || 0) + " / " + (status.max_points || 16),
        "频率：" + ((status.frequencies_hz || []).length
          ? status.frequencies_hz.map((value) => Number(value).toFixed(1) + " Hz").join(", ")
          : "尚无"),
        status.metadata && profile === "rc"
          ? "元件：" + status.metadata.actual_r_ohm + " Ω / " +
            (Number(status.metadata.actual_c_f) * 1e9).toFixed(2) + " nF"
          : "",
        status.metadata && profile === "generic"
          ? "被测系统：" + (status.metadata.dut_name || "—") +
            (status.metadata.dut_model ? " · " + status.metadata.dut_model : "")
          : "",
        status.last_rejected
          ? "最近失败：目标 " +
            Number(status.last_rejected.target_hz).toFixed(3) +
            " Hz，估计 " +
            Number(status.last_rejected.estimated_frequency_hz).toFixed(3) +
            " Hz，残差 " +
            Number(status.last_rejected.relative_residual).toFixed(5)
          : "",
      ].filter(Boolean).join("\n");
      startResponseRecordButton.disabled =
        hardwareBusy || currentHardwareMode !== "M4" ||
        status.active || Boolean(status.can_save);
      stopResponseRecordButton.disabled = hardwareBusy || !status.active;
      discardResponseRecordButton.disabled =
        hardwareBusy || (!status.active && !status.can_save);
      captureResponsePointButton.disabled =
        hardwareBusy || !status.active || status.point_count >= status.max_points;
      document.getElementById("saveResponseButton").disabled =
        hardwareBusy || status.point_count < 3;
    } catch (error) {
      responseRecordStatus.textContent = "响应记录状态读取失败：" + error.message;
    }
  }

  async function refreshLiveAnalysis() {
    try {
      const result = await request("/bx/api/live/status");
      const runtime = result.runtime || {};
      const summary = result.summary || {};
      const latest = runtime.latest || null;
      const peaks = latest && latest.metrics ? latest.metrics.peaks || [] : [];
      analysisLiveText.textContent = [
        "来源模式：" + (runtime.mode === "LIVE" ? "实时频谱" :
          runtime.mode === "M4" ? "电路测量" : "未运行"),
        "运行状态：" + phaseLabel(runtime.mode, runtime.phase),
        "记录编号：" + (runtime.run_id || "尚无"),
        "已采集帧：" + (runtime.frames || 0),
        "已接收状态：" + (summary.accepted || 0),
        "重复忽略：" + (summary.duplicates || 0),
        "无帧跳过：" + (summary.skipped || 0),
        "缺口数：" + ((summary.gaps || []).length),
        "平均累计：" + (summary.feature_average_count || 0) + " 份",
        "保持累计：" + (summary.feature_hold_count || 0) + " 份",
        "当前主峰：" + (peaks.length
          ? Number(peaks[0].frequency_hz || 0).toFixed(2) + " Hz"
          : "暂无"),
      ].join("\n");
    } catch (error) {
      analysisLiveText.textContent = "实时分析状态读取失败：" + error.message;
    }
    await refreshAnalysisRecord();
  }

  async function refreshAnalysisRecord() {
    try {
      const status = await request("/bx/api/analysis/record/status");
      analysisRecordStatus.textContent = [
        "记录状态：" + (status.active ? "正在记录" : "未在记录"),
        "实时采集状态：" + (status.runtime_phase || "无"),
        "实时采集帧：" + (status.runtime_frames || 0),
        "采集总帧：" + (status.total_frames || 0),
        "完整频谱：" + (status.saved_complete_count || 0) +
          " / " + (status.max_complete_frames || 0),
        "指标行：" + (status.saved_metric_count || 0) +
          " / " + (status.max_metric_rows || 0),
        "完整谱溢出：" + (status.dropped_complete_count || 0),
        "指标溢出：" + (status.dropped_metric_count || 0),
        (status.observer_errors && status.observer_errors.length)
          ? "观察器错误：" + status.observer_errors.slice(-1)[0]
          : "观察器：正常",
        status.error ? "错误：" + status.error : "",
      ].filter(Boolean).join("\n");
      startAnalysisRecordButton.disabled =
        status.active || Boolean(status.can_save) ||
        status.runtime_phase !== "RUNNING";
      stopAnalysisRecordButton.disabled = !status.active;
      discardAnalysisRecordButton.disabled =
        !status.active && !status.can_save;
      saveAnalysisButton.disabled = !(
        status.can_save ||
        (status.active && (
          status.saved_complete_count > 0 ||
          status.saved_metric_count > 0
        ))
      );
    } catch (error) {
      analysisRecordStatus.textContent = "记录状态读取失败：" + error.message;
    }
  }

  function recordTypeLabel(record) {
    if (record.record_type !== "response") return "深入分析";
    if (record.response_kind === "generic_system") return "通用系统频率响应";
    return "RC 低通滤波器频率响应";
  }

  function hideResponseDownloads() {
    downloadResponseCsv.hidden = true;
    downloadResponseJson.hidden = true;
    downloadResponseCsv.removeAttribute("href");
    downloadResponseJson.removeAttribute("href");
  }

  function clearRecordViewer() {
    recordViewerFrame.hidden = true;
    recordViewerFrame.removeAttribute("src");
    responseRecordViewer.hidden = true;
    responseRecordImage.removeAttribute("src");
    responseRecordTable.replaceChildren();
    hideResponseDownloads();
  }

  function showResponseDownloads(recordId) {
    const base = "/bx/api/response-record/download?record_id=" +
      encodeURIComponent(recordId);
    downloadResponseCsv.href = base + "&format=csv";
    downloadResponseJson.href = base + "&format=json";
    downloadResponseCsv.hidden = false;
    downloadResponseJson.hidden = false;
  }

  async function refreshRecords() {
    try {
      const result = await request("/bx/api/records");
      const records = result.records || [];
      recordsList.replaceChildren();
      if (!records.length) {
        const empty = document.createElement("div");
        empty.className = "record-empty";
        empty.textContent = "尚无用户记录。请在“深入分析”或“频率响应”中主动保存。";
        recordsList.appendChild(empty);
        currentRecordId = null;
        recordDetailText.textContent = "选择一条记录查看详情。";
        deleteRecordButton.disabled = true;
        clearRecordViewer();
        return;
      }
      for (const record of records) {
        const item = document.createElement("div");
        item.className = "record-item";
        const info = document.createElement("div");
        const title = document.createElement("span");
        title.className = "record-title";
        title.textContent = record.title;
        const meta = document.createElement("span");
        meta.className = "record-meta";
        meta.textContent = recordTypeLabel(record) + " · " +
          record.created + " · " + record.source;
        info.append(title, meta);
        const button = document.createElement("button");
        button.className = "button secondary";
        button.type = "button";
        button.textContent = "查看";
        button.addEventListener("click", () => loadRecord(record.record_id));
        item.append(info, button);
        recordsList.appendChild(item);
      }
    } catch (error) {
      recordsList.textContent = "记录读取失败：" + error.message;
    }
  }

  async function loadRecord(recordId) {
    clearRecordViewer();
    try {
      const record = await request(
        "/bx/api/records/load?record_id=" + encodeURIComponent(recordId));
      currentRecordId = record.record_id;
      deleteRecordButton.disabled = false;
      const lines = [
        "名称：" + record.title,
        "类型：" + recordTypeLabel(record),
        "时间：" + record.created,
        "来源：" + record.source,
      ];
      if (record.record_type === "analysis") {
        const payload = record.payload || {};
        if (payload.summary) {
          const summary = payload.summary || {};
          lines.push("接收状态：" + (summary.accepted || 0));
          lines.push("重复忽略：" + (summary.duplicates || 0));
          lines.push("缺口数：" + ((summary.gaps || []).length));
        }
        if (record.record_status) {
          lines.push("记录质量：" + ({
            COMPLETE_REPLAY: "完整多帧回放",
            SINGLE_FRAME: "单帧记录",
            METRICS_ONLY: "仅指标记录",
          }[record.record_status] || record.record_status));
        }
      } else {
        const capture = (record.payload || {}).capture || {};
        if (capture.label) lines.push("采集记录：" + capture.label);
        if (capture.fs_hz) lines.push("采样率：" + Number(capture.fs_hz).toFixed(2) + " Hz");
        if (capture.channel_rms) {
          lines.push("左/右 RMS：" + capture.channel_rms.map(
            (value) => Number(value).toFixed(6)).join(" / "));
        }
        if (record.record_status) lines.push("记录质量：" + record.record_status);
        if (record.conditions) {
          if (record.response_kind === "generic_system") {
            lines.push("被测系统：" + (record.conditions.dut_name || "—") +
              (record.conditions.dut_model ? " · " + record.conditions.dut_model : ""));
          } else {
            lines.push("元件：" + record.conditions.actual_r_ohm + " Ω / " +
              (Number(record.conditions.actual_c_f) * 1e9).toFixed(2) + " nF");
          }
          lines.push("温度：" + record.conditions.temperature);
        }
        if (record.fitted_cutoff_hz) {
          lines.push("拟合截止：" + Number(record.fitted_cutoff_hz).toFixed(3) + " Hz");
        }
      }
      recordDetailText.textContent = lines.join("\n");
      if (record.record_type === "analysis" && record.record_status) {
        responseRecordViewer.hidden = true;
        recordViewerFrame.hidden = false;
        recordViewerFrame.src = "/bx/?source=user&record_id=" +
          encodeURIComponent(record.record_id);
      } else if (record.record_type === "response" &&
                 Array.isArray(record.points) && record.points.length >= 3) {
        recordViewerFrame.hidden = true;
        responseRecordViewer.hidden = false;
        showResponseDownloads(record.record_id);
        responseRecordImage.src = "/bx/api/response-record/plot?record_id=" +
          encodeURIComponent(record.record_id);
        responseRecordTable.replaceChildren();
        for (const point of record.points) {
          const row = document.createElement("tr");
          for (const value of [
            Number(point.target_hz).toFixed(1),
            Number(point.H_cal_calibration_mean.gain_db).toFixed(4),
            Number(point.H_cal_calibration_mean.phase_deg).toFixed(4),
            point.calibration_used ? "已校准" : "未校准",
          ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
          }
          responseRecordTable.appendChild(row);
        }
      } else {
        clearRecordViewer();
      }
    } catch (error) {
      recordDetailText.textContent = "记录读取失败：" + error.message;
    }
  }

  async function saveAnalysis() {
    const title = document.getElementById("analysisRecordTitle").value.trim();
    analysisSaveResult.textContent = "正在保存…";
    try {
      const record = await request(
        "/bx/api/records/save-analysis", {title});
      analysisSaveResult.textContent = "已保存：" + record.title;
      await refreshRecords();
      await refreshAnalysisRecord();
    } catch (error) {
      analysisSaveResult.textContent = "保存失败：" + error.message;
    }
  }

  async function saveResponse() {
    const title = document.getElementById("responseRecordTitle").value.trim();
    responseSaveResult.textContent = "正在保存…";
    try {
      const record = await request(
        `/bx/api/response/${responseProfile()}/save`, {title});
      responseSaveResult.textContent = "已保存：" + record.title;
      await refreshRecords();
      await refreshResponseRecord();
    } catch (error) {
      responseSaveResult.textContent = "保存失败：" + error.message;
    }
  }

  async function startResponseRecord() {
    responseSaveResult.textContent = "正在开始响应记录…";
    try {
      const profile = responseProfile();
      const common = {
        temperature: document.getElementById("responseTemperature").value,
        generator: document.getElementById("responseGenerator").value,
      };
      const payload = profile === "rc" ? {
        ...common,
        actual_r_ohm: Number(document.getElementById("responseResistance").value),
        actual_c_nf: Number(document.getElementById("responseCapacitance").value),
      } : {
        ...common,
        dut_name: document.getElementById("responseDutName").value,
        dut_model: document.getElementById("responseDutModel").value,
        dut_serial: document.getElementById("responseDutSerial").value,
        input_description: document.getElementById("responseInputDescription").value,
        output_description: document.getElementById("responseOutputDescription").value,
        attenuation_note: document.getElementById("responseAttenuationNote").value,
      };
      await request(`/bx/api/response/${profile}/start`, payload);
      responseSaveResult.textContent = "响应记录已开始。";
      await refreshResponseRecord();
    } catch (error) {
      responseSaveResult.textContent = "开始失败：" + error.message;
    }
  }

  async function captureResponsePoint() {
    responseSaveResult.textContent = "正在采集并拟合当前频点…";
    try {
      const result = await request(
        `/bx/api/response/${responseProfile()}/capture`, {
        target_hz: Number(document.getElementById("responseTargetHz").value),
        label: document.getElementById("responseCaptureLabel").value,
      });
      responseSaveResult.textContent =
        "频点已采集：" + result.capture.label +
        "\n采样率：" + Number(result.capture.fs_hz).toFixed(2) + " Hz" +
        "\n已记录频点数：" + result.response.point_count;
      await refreshResponseRecord();
    } catch (error) {
      responseSaveResult.textContent = "频点采集失败：" + error.message;
      await refreshResponseRecord();
    }
  }

  for (const tab of tabs) {
    tab.addEventListener("click", () => selectPanel(tab.dataset.panel));
  }
  document.getElementById("enterM4Button").addEventListener("click", () =>
    command("/bx/api/hardware/m4/enter", {}, m4Result, "已进入电路测量模式"));
  document.getElementById("configureM4Button").addEventListener("click", () =>
    command("/bx/api/hardware/m4/configure", {}, m4Result, "codec 与采样率配置完成"));
  document.getElementById("selfTestM4Button").addEventListener("click", () =>
    command("/bx/api/hardware/m4/selftest", {}, m4Result, "双声道计数器自检通过"));
  document.getElementById("captureM4Button").addEventListener("click", () =>
    command(
      "/bx/api/hardware/m4/capture",
      {label: inputLabel.value},
      m4Result,
      "双声道采集完成",
    ));
  responseProfileSelect.addEventListener("change", () => {
    const generic = responseProfile() === "generic";
    responseRcFields.hidden = generic;
    responseGenericFields.hidden = !generic;
    responseSaveResult.textContent = generic
      ? "通用系统模式不要求 R/C；至少 3 个频点后可保存。"
      : "RC 模式会计算理论曲线和一阶拟合。";
    refreshResponseRecord();
  });
  document.getElementById("restoreFftButton").addEventListener("click", () =>
    command("/bx/api/hardware/fft/restore", {}, m4Result, "已恢复实时频谱模式"));
  document.getElementById("saveAnalysisButton").addEventListener("click", saveAnalysis);
  startAnalysisRecordButton.addEventListener("click", async () => {
    analysisSaveResult.textContent = "正在开始记录…";
    try {
      await request("/bx/api/analysis/record/start", {
        max_complete_frames: Number(analysisFrameLimit.value),
      });
      analysisSaveResult.textContent = "记录已开始。";
      await refreshAnalysisRecord();
    } catch (error) {
      analysisSaveResult.textContent = "开始失败：" + error.message;
    }
  });
  stopAnalysisRecordButton.addEventListener("click", async () => {
    analysisSaveResult.textContent = "正在停止记录…";
    try {
      await request("/bx/api/analysis/record/stop", {});
      analysisSaveResult.textContent = "记录已停止，可以保存。";
      await refreshAnalysisRecord();
    } catch (error) {
      analysisSaveResult.textContent = "停止失败：" + error.message;
    }
  });
  discardAnalysisRecordButton.addEventListener("click", async () => {
    if (!window.confirm("确认放弃当前记录？此操作不可恢复。")) return;
    try {
      await request("/bx/api/analysis/record/discard", {});
      analysisSaveResult.textContent = "当前记录已放弃。";
      await refreshAnalysisRecord();
    } catch (error) {
      analysisSaveResult.textContent = "放弃失败：" + error.message;
    }
  });
  document.getElementById("saveResponseButton").addEventListener("click", saveResponse);
  startResponseRecordButton.addEventListener("click", startResponseRecord);
  stopResponseRecordButton.addEventListener("click", async () => {
    try {
      await request(
        `/bx/api/response/${responseProfile()}/stop`, {});
      responseSaveResult.textContent = "响应记录已停止，可以保存。";
      await refreshResponseRecord();
    } catch (error) {
      responseSaveResult.textContent = "停止失败：" + error.message;
    }
  });
  discardResponseRecordButton.addEventListener("click", async () => {
    if (!window.confirm("确认放弃当前频率响应记录？")) return;
    try {
      await request(
        `/bx/api/response/${responseProfile()}/discard`, {});
      responseSaveResult.textContent = "当前响应记录已放弃。";
      await refreshResponseRecord();
    } catch (error) {
      responseSaveResult.textContent = "放弃失败：" + error.message;
    }
  });
  captureResponsePointButton.addEventListener("click", captureResponsePoint);
  document.getElementById("refreshRecordsButton").addEventListener("click", refreshRecords);
  deleteRecordButton.addEventListener("click", async () => {
    if (!currentRecordId) return;
    if (!window.confirm("确认删除当前记录？此操作不可恢复。")) return;
    try {
      await request("/bx/api/records/delete", {record_id: currentRecordId});
      currentRecordId = null;
      recordDetailText.textContent = "记录已删除。";
      deleteRecordButton.disabled = true;
      clearRecordViewer();
      await refreshRecords();
    } catch (error) {
      recordDetailText.textContent = "删除失败：" + error.message;
    }
  });

  selectPanel("spectrum");
  refreshHardware();
  refreshLiveAnalysis();
  setInterval(() => {
    if (activePanel === "analysis") refreshLiveAnalysis();
    if (activePanel === "m4") refreshHardware();
  }, 1000);
})();
