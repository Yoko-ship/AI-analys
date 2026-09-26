import { safeNumber } from "./format.jsx";

function buildSparkline(values, width = 220, height = 74) {
  const points = (Array.isArray(values) ? values : []).map((value) => safeNumber(value)).filter((value) => value !== null);
  if (!points.length) return null;

  let min = Math.min(...points);
  let max = Math.max(...points);
  if (min === max) {
    min -= 1;
    max += 1;
  }

  const padding = { left: 8, right: 8, top: 10, bottom: 12 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const range = max - min || 1;
  const x = (index) => padding.left + (points.length <= 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (value) => padding.top + ((max - value) / range) * innerHeight;
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(point).toFixed(2)}`).join(" ");
  const areaPath = `${path} L ${x(points.length - 1).toFixed(2)} ${height - padding.bottom} L ${x(0).toFixed(2)} ${height - padding.bottom} Z`;

  return { width, height, points, path, areaPath, latest: points.at(-1), min, max };
}

function scorePercent(score) {
  if (score === null || score === undefined || score === "") return null;
  const value = Number(score);
  if (!Number.isFinite(value)) return null;
  return clampPercent(value <= 10 ? value * 10 : value);
}

function scoreTone(score) {
  const value = scorePercent(score);
  if (value === null) return "neutral";
  if (value >= 70) return "good";
  if (value >= 45) return "warning";
  return "danger";
}

function clampPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  return Math.max(0, Math.min(100, num));
}

export { buildSparkline, clampPercent, scorePercent, scoreTone };
