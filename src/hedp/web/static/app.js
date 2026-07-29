"use strict";

const toast = document.querySelector("#toast");
let toastTimer;
let solarHistory = [];

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

async function loadSummary() {
  try {
    const response = await fetch("/api/summary", { cache: "no-store" });
    if (!response.ok) throw new Error("summary unavailable");
    const data = await response.json();
    setText("#solar", displayNumber(data.energy.solar_kw, 1));
    setText("#battery", displayNumber(data.energy.battery_percent));
    const battery = Number.isFinite(data.energy.battery_percent)
      ? Math.min(100, Math.max(0, data.energy.battery_percent))
      : 0;
    document.querySelector("#battery-bar").style.width = `${battery}%`;
    setText("#temperature", displayNumber(data.climate.temperature_c, 1));
    setText("#humidity", displayNumber(data.climate.humidity_percent));
    setText("#co2", displayNumber(data.climate.co2_ppm));
    setText("#today-energy", displayNumber(data.energy.today_kwh, 1));
    setText(
      "#self-consumption",
      displayNumber(data.energy.self_consumption_percent),
    );
    setText("#data-mode", data.mode === "live_read_only" ? "READ ONLY" : "SHADOW");
    setText("#data-quality", data.quality?.status || "demo");
    solarHistory = Array.isArray(data.energy.history) ? data.energy.history : [];
    drawSolarChart();
    for (const device of data.devices || []) {
      const button = document.querySelector(`[data-action="${device.kind}"]`);
      if (button) button.querySelector("small").textContent = device.state;
    }
  } catch {
    showToast("表示用データを読み込めませんでした");
  }
}

function drawSolarChart() {
  const canvas = document.querySelector("#solar-chart");
  if (!canvas) return;
  const bounds = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, bounds.width, bounds.height);
  if (solarHistory.length < 2) return;

  const width = bounds.width;
  const height = bounds.height;
  const padding = { top: 16, right: 5, bottom: 12, left: 5 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maximum =
    Math.max(
      ...solarHistory.map((point) =>
        Number.isFinite(point.solar_kw) ? point.solar_kw : 0,
      ),
      1,
    ) * 1.12;
  const points = solarHistory.map((point, index) => ({
    x: padding.left + (index / (solarHistory.length - 1)) * chartWidth,
    y: padding.top + chartHeight - (point.solar_kw / maximum) * chartHeight,
  }));
  const isDark = document.body.classList.contains("dark");

  context.strokeStyle = isDark ? "rgba(255,255,255,.09)" : "rgba(60,60,67,.09)";
  context.lineWidth = 1;
  for (let line = 0; line < 4; line += 1) {
    const y = padding.top + (line / 3) * chartHeight;
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
  }

  const fill = context.createLinearGradient(0, padding.top, 0, height);
  fill.addColorStop(0, "rgba(255,159,10,.34)");
  fill.addColorStop(1, "rgba(255,204,0,.015)");
  context.beginPath();
  context.moveTo(points[0].x, height - padding.bottom);
  for (const point of points) context.lineTo(point.x, point.y);
  context.lineTo(points.at(-1).x, height - padding.bottom);
  context.closePath();
  context.fillStyle = fill;
  context.fill();

  context.beginPath();
  context.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) context.lineTo(point.x, point.y);
  context.strokeStyle = "#ff9f0a";
  context.lineWidth = 3;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.stroke();
}

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
  drawSolarChart();
});

window.addEventListener("resize", drawSolarChart);
loadSummary();
