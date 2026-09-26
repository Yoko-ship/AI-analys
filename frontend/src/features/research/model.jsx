import { safeNumber } from "../../shared/format.jsx";

function buildSeriesChart(series, language) {
  const points = Array.isArray(series) ? series : [];
  const filtered = points
    .map((row) => ({
      year: row?.year,
      revenue: safeNumber(row?.revenue),
      profit: safeNumber(row?.net_income),
      debt: safeNumber(row?.total_liabilities ?? row?.total_debt ?? row?.debt),
    }))
    .filter((row) => row.year !== undefined && row.year !== null && (row.revenue !== null || row.profit !== null || row.debt !== null));

  if (filtered.length < 2) return null;

  const width = 1000;
  const height = 340;
  const padding = { left: 74, right: 24, top: 28, bottom: 44 };
  const allValues = filtered.flatMap((row) => [row.revenue, row.profit, row.debt]).filter((value) => Number.isFinite(value));
  let min = Math.min(...allValues);
  let max = Math.max(...allValues);
  if (min > 0) min = 0;
  if (max < 0) max = 0;
  const range = max - min === 0 ? 1 : max - min;
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (filtered.length <= 1 ? innerWidth / 2 : (index / (filtered.length - 1)) * innerWidth);
  const y = (value) => padding.top + ((max - value) / range) * innerHeight;
  const line = (arr) =>
    arr
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(Number.isFinite(point) ? point : min).toFixed(2)}`)
      .join(" ");

  const revenuePoints = filtered.map((row) => row.revenue ?? min);
  const profitPoints = filtered.map((row) => row.profit ?? min);
  const debtPoints = filtered.map((row) => row.debt ?? min);
  const revenuePath = line(revenuePoints);
  const profitPath = line(profitPoints);
  const debtPath = line(debtPoints);
  const zeroY = y(0);
  const areaPath = `${revenuePath} L ${x(filtered.length - 1).toFixed(2)} ${zeroY.toFixed(2)} L ${x(0).toFixed(2)} ${zeroY.toFixed(2)} Z`;

  const yTicks = Array.from({ length: 5 }, (_, idx) => {
    const ratio = idx / 4;
    const value = max - ratio * range;
    const yy = padding.top + ratio * innerHeight;
    return { value, y: yy };
  });

  const latest = filtered.at(-1);
  const previous = filtered.at(-2) || {};
  const revenueChange =
    Number.isFinite(latest.revenue) && Number.isFinite(previous.revenue)
      ? ((latest.revenue - previous.revenue) / Math.abs(previous.revenue || 1)) * 100
      : null;
  const profitChange =
    Number.isFinite(latest.profit) && Number.isFinite(previous.profit)
      ? ((latest.profit - previous.profit) / Math.abs(previous.profit || 1)) * 100
      : null;
  const debtChange =
    Number.isFinite(latest.debt) && Number.isFinite(previous.debt)
      ? ((latest.debt - previous.debt) / Math.abs(previous.debt || 1)) * 100
      : null;

  return {
    width,
    height,
    filtered,
    areaPath,
    revenuePath,
    profitPath,
    debtPath,
    yTicks,
    latest,
    revenueChange,
    profitChange,
    debtChange,
    x,
    y,
  };
}

export { buildSeriesChart };
