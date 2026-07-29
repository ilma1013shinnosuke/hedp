"use strict";

const toast = document.querySelector("#toast");
const periodLabels = { day: "ENERGY · TODAY", "7d": "ENERGY · 7 DAYS", "30d": "ENERGY · 30 DAYS" };
let toastTimer;
let solarHistory = [];
let batteryHistory = [];
let currentPeriod = "day";
let requestSequence = 0;

function displayNumber(value, decimals = 0) {
  return Number.isFinite(value) ? value.toFixed(decimals) : "—";
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) element.textContent = value;
}

function showToast(message) {
  toast.lastElementChild.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2400);
}

function localTime(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("ja-JP", {
    month: currentPeriod === "day" ? undefined : "numeric",
    day: currentPeriod === "day" ? undefined : "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function observationLabel(observation, shadow = false) {
  if (shadow) return { text: "匿名サンプル", status: "good" };
  const status = observation?.quality?.status || "missing";
  const observedAt = localTime(observation?.observed_at);
  if (status === "good") return { text: `更新 ${observedAt || "確認済み"}`, status };
  if (status === "stale") return { text: `古い値 · ${observedAt || "時刻不明"}`, status };
  if (status === "invalid") return { text: "確認が必要な値", status };
  return { text: "取得不能", status: "missing" };
}

function setObservation(selector, observation, shadow) {
  const element = document.querySelector(selector);
  if (!element) return;
  const label = observationLabel(observation, shadow);
  element.textContent = label.text;
  element.className = `metric-meta ${label.status}`;
}

function updateWarning(data) {
  const warning = document.querySelector("#data-warning");
  const observations = Object.values(data.energy?.observations || {});
  const statuses = observations.map((item) => item?.quality?.status);
  const unavailable = data.mode === "unavailable";
  const invalid = statuses.includes("invalid");
  const missing = statuses.includes("missing");
  const stale = statuses.includes("stale");
  warning.hidden = !(unavailable || invalid || missing || stale);
  if (unavailable) {
    setText("#data-warning-text", "表示用データへ接続できません");
  } else if (invalid) {
    setText("#data-warning-text", "確認が必要な値があります");
  } else if (missing) {
    setText("#data-warning-text", "取得できていない項目があります");
  } else if (stale) {
    setText("#data-warning-text", "一部の値が古くなっています");
  }
}

async function loadSummary(period = currentPeriod) {
  const sequence = ++requestSequence;
  try {
    const response = await fetch(`/api/summary?period=${encodeURIComponent(period)}`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("summary unavailable");
    const data = await response.json();
    if (sequence !== requestSequence) return;
    currentPeriod = data.period || period;
    const energy = data.energy || {};
    const observations = energy.observations || {};
    const shadow = data.mode === "shadow";

    setText("#solar", displayNumber(energy.solar_kw, 1));
    setText("#battery", displayNumber(energy.battery_percent));
    setObservation("#solar-meta", observations.solar_kw, shadow);
    setObservation("#battery-meta", observations.battery_percent, shadow);
    const battery = Number.isFinite(energy.battery_percent)
      ? Math.min(100, Math.max(0, energy.battery_percent))
      : 0;
    document.querySelector("#battery-bar").style.width = `${battery}%`;
    setText("#temperature", displayNumber(data.climate?.temperature_c, 1));
    setText("#humidity", displayNumber(data.climate?.humidity_percent));
    setText("#co2", displayNumber(data.climate?.co2_ppm));
    setText("#today-energy", displayNumber(energy.today_kwh, 1));
    setText("#self-consumption", displayNumber(energy.self_consumption_percent));
    setText("#data-mode", data.mode === "live_read_only" ? "READ ONLY" : data.mode === "unavailable" ? "UNAVAILABLE" : "SHADOW");
    setText("#data-quality", data.quality?.status || "demo");
    setText("#data-observed-at", localTime(data.observed_at) || (shadow ? "匿名値" : "更新時刻なし"));
    setText("#chart-period-label", periodLabels[currentPeriod] || periodLabels.day);
    solarHistory = Array.isArray(energy.history) ? energy.history : [];
    batteryHistory = Array.isArray(energy.battery_history) ? energy.battery_history : [];
    updateWarning(data);
    drawEnergyChart();
    for (const device of data.devices || []) {
      const button = document.querySelector(`[data-action="${device.kind}"]`);
      if (button) button.querySelector("small").textContent = device.state;
    }
  } catch {
    if (sequence !== requestSequence) return;
    document.querySelector("#data-warning").hidden = false;
    setText("#data-warning-text", "表示用データを読み込めませんでした");
    showToast("表示用データを読み込めませんでした");
  }
}

function plotSeries(context, history, valueKey, bounds, color, fillColor = null) {
  const values = history
    .map((point) => point[valueKey])
    .filter((value) => Number.isFinite(value));
  if (values.length < 2) return;
  const maximum = Math.max(...values, 1) * (valueKey === "solar_kw" ? 1.12 : 1);
  const points = history
    .map((point, index) => ({
      value: point[valueKey],
      x: bounds.left + (index / Math.max(history.length - 1, 1)) * bounds.width,
      y: bounds.top + bounds.height - (point[valueKey] / maximum) * bounds.height,
    }))
    .filter((point) => Number.isFinite(point.value));
  if (points.length < 2) return;

  if (fillColor) {
    const fill = context.createLinearGradient(0, bounds.top, 0, bounds.top + bounds.height);
    fill.addColorStop(0, fillColor);
    fill.addColorStop(1, "rgba(255,204,0,.015)");
    context.beginPath();
    context.moveTo(points[0].x, bounds.top + bounds.height);
    for (const point of points) context.lineTo(point.x, point.y);
    context.lineTo(points.at(-1).x, bounds.top + bounds.height);
    context.closePath();
    context.fillStyle = fill;
    context.fill();
  }

  context.beginPath();
  context.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) context.lineTo(point.x, point.y);
  context.strokeStyle = color;
  context.lineWidth = 3;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.stroke();
}

function updateChartAxis() {
  const axis = document.querySelector("#chart-axis");
  const source = solarHistory.length ? solarHistory : batteryHistory;
  axis.replaceChildren();
  if (!source.length) return;
  const count = Math.min(5, source.length);
  const indexes = Array.from({ length: count }, (_, index) =>
    Math.round(index * (source.length - 1) / Math.max(count - 1, 1)),
  );
  for (const index of [...new Set(indexes)]) {
    const label = document.createElement("span");
    label.textContent = source[index].time || localTime(source[index].observed_at) || "—";
    axis.appendChild(label);
  }
}

function drawEnergyChart() {
  const canvas = document.querySelector("#solar-chart");
  if (!canvas) return;
  const bounds = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, bounds.width, bounds.height);
  updateChartAxis();

  const padding = { top: 16, right: 5, bottom: 12, left: 5 };
  const chart = {
    top: padding.top,
    left: padding.left,
    width: bounds.width - padding.left - padding.right,
    height: bounds.height - padding.top - padding.bottom,
  };
  const isDark = document.body.classList.contains("dark");
  context.strokeStyle = isDark ? "rgba(255,255,255,.09)" : "rgba(60,60,67,.09)";
  context.lineWidth = 1;
  for (let line = 0; line < 4; line += 1) {
    const y = chart.top + (line / 3) * chart.height;
    context.beginPath();
    context.moveTo(chart.left, y);
    context.lineTo(chart.left + chart.width, y);
    context.stroke();
  }
  plotSeries(context, solarHistory, "solar_kw", chart, "#ff9f0a", "rgba(255,159,10,.34)");
  plotSeries(context, batteryHistory, "battery_percent", chart, "#00a98f");
}

document.querySelectorAll("[data-period]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-period]").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    loadSummary(button.dataset.period);
  });
});

document.querySelectorAll("[data-section]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-section]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    showToast(`${button.getAttribute("aria-label")} — 次の版で接続します`);
  });
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => {
    showToast(`${button.getAttribute("aria-label")} — 実機へは送信しません`);
  });
});

document.querySelector("#theme-toggle").addEventListener("click", () => {
  document.body.classList.toggle("dark");
  drawEnergyChart();
});

window.addEventListener("resize", drawEnergyChart);
loadSummary();
