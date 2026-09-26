import { normalizeLanguage } from "../../shared/i18n.jsx";
import { formatCompactNumber, formatRatio } from "../../shared/format.jsx";
import { ct } from "./copy.jsx";
import React from "react";

const COMPARE_COLORS = ["#6ef0c1", "#f5b84d", "#7dd3fc"];

const COMPARE_TABLE_TITLES = {
  ru: {
    overview: "Обзор",
    profitability: "Прибыльность",
    growth: "Рост",
    balance: "Баланс и риск",
    market: "Рынок",
    documents: "Отчеты",
    category_scores: "Сводные категории",
  },
  en: {
    overview: "Overview",
    profitability: "Profitability",
    growth: "Growth",
    balance: "Balance and risk",
    market: "Market",
    documents: "Reports",
    category_scores: "Category scores",
  },
  uz: {
    overview: "Umumiy",
    profitability: "Rentabellik",
    growth: "O'sish",
    balance: "Balans va risk",
    market: "Bozor",
    documents: "Hisobotlar",
    category_scores: "Kategoriya ballari",
  },
};

const COMPARE_LEADER_LABELS = {
  ru: {
    overall_leader: "Общий лидер",
    profitability_leader: "Прибыльность",
    roe_leader: "ROE",
    balance_quality_leader: "Качество баланса",
    market_liquidity_leader: "Ликвидность",
    lowest_debt_ratio: "Минимальная долговая нагрузка",
  },
  en: {
    overall_leader: "Overall leader",
    profitability_leader: "Profitability",
    roe_leader: "ROE",
    balance_quality_leader: "Balance quality",
    market_liquidity_leader: "Liquidity",
    lowest_debt_ratio: "Lowest debt load",
  },
  uz: {
    overall_leader: "Umumiy lider",
    profitability_leader: "Rentabellik",
    roe_leader: "ROE",
    balance_quality_leader: "Balans sifati",
    market_liquidity_leader: "Likvidlik",
    lowest_debt_ratio: "Eng past qarz yuki",
  },
};

function compareTableTitle(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_TABLE_TITLES[lang]?.[key] ?? key.replaceAll("_", " ");
}

function compareLeaderLabel(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_LEADER_LABELS[lang]?.[key] ?? key.replaceAll("_", " ");
}

function formatCompareValue(value, language, unit = "") {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  const normalizedUnit = String(unit || "").trim();
  const formatted = Math.abs(num) >= 1000 ? formatCompactNumber(num, language, 2) : formatRatio(num, 2, language);
  if (normalizedUnit === "%") return `${formatted}%`;
  if (normalizedUnit === "x") return `${formatted}x`;
  if (normalizedUnit.startsWith("/")) return `${formatted}${normalizedUnit}`;
  if (!normalizedUnit) return formatted;
  return `${formatted} ${normalizedUnit}`;
}

function formatCompareCell(cell, column, language) {
  if (cell && typeof cell === "object" && !Array.isArray(cell)) {
    return {
      value: formatCompareValue(cell.raw, language, column?.unit),
      normalized: cell.normalized,
      rank: cell.rank,
    };
  }
  return {
    value: formatCompareValue(cell, language, column?.unit),
    normalized: null,
    rank: null,
  };
}

function getCompareSeriesData(series) {
  return Array.isArray(series?.data) ? series.data : Array.isArray(series?.values) ? series.values : [];
}

function getCompareAxisLabel(item) {
  if (!item || typeof item !== "object") return String(item || "");
  return item.ticker || item.company_name || item.label || "";
}

function CompareLeaderCards({ leaders, language }) {
  const entries = Object.entries(leaders || {}).filter(([, value]) => value);
  if (!entries.length) {
    return <div className="empty-state"><p className="empty-copy">{ct(language, "noData")}</p></div>;
  }

  return (
    <div className="compare-leader-grid">
      {entries.map(([key, value], index) => (
        <article key={key} className="compare-leader-card" style={{ "--series-color": COMPARE_COLORS[index % COMPARE_COLORS.length] }}>
          <span>{compareLeaderLabel(language, key)}</span>
          <strong>{value.ticker || value.company || "—"}</strong>
          <p>{formatCompareValue(value.value, language)}</p>
        </article>
      ))}
    </div>
  );
}

function CompareRanking({ title, rows, scoreKey, language }) {
  const items = Array.isArray(rows) ? rows : [];
  if (!items.length) return null;
  return (
    <article className="compare-ranking-card">
      <h3>{title}</h3>
      <div className="compare-ranking-list">
        {items.map((item) => (
          <div key={`${title}-${item.rank}-${item.ticker || item.company}`} className="compare-ranking-row">
            <span className="compare-rank">#{item.rank}</span>
            <span className="compare-company">{item.ticker || item.company || "—"}</span>
            <strong>{formatCompareValue(item[scoreKey], language, scoreKey.endsWith("score") ? "/100" : "")}</strong>
          </div>
        ))}
      </div>
    </article>
  );
}

function CompareRadarChart({ chart, language }) {
  const labels = Array.isArray(chart?.labels) ? chart.labels : [];
  const datasets = Array.isArray(chart?.datasets) ? chart.datasets : [];
  const size = 360;
  const center = size / 2;
  const radius = 116;
  const labelRadius = 150;

  if (labels.length < 3 || !datasets.length) {
    return <div className="compare-chart-empty">{ct(language, "noData")}</div>;
  }

  const point = (index, value, customRadius = radius) => {
    const angle = -Math.PI / 2 + (index / labels.length) * Math.PI * 2;
    const bounded = Math.max(0, Math.min(100, Number(value) || 0)) / 100;
    const r = customRadius * bounded;
    return {
      x: center + Math.cos(angle) * r,
      y: center + Math.sin(angle) * r,
    };
  };

  const ringPath = (level) =>
    labels
      .map((_, index) => {
        const p = point(index, 100, radius * level);
        return `${index === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
      })
      .join(" ") + " Z";

  return (
    <div className="compare-radar-wrap">
      <svg className="compare-radar" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={chart.title || ct(language, "charts")}>
        {[0.25, 0.5, 0.75, 1].map((level) => (
          <path key={level} className="compare-radar-ring" d={ringPath(level)} />
        ))}
        {labels.map((label, index) => {
          const edge = point(index, 100);
          const textPoint = point(index, 100, labelRadius);
          return (
            <g key={label.key || label.label || index}>
              <line className="compare-radar-axis" x1={center} y1={center} x2={edge.x} y2={edge.y} />
              <text className="compare-radar-label" x={textPoint.x} y={textPoint.y} textAnchor="middle">
                {label.label || label.key || index + 1}
              </text>
            </g>
          );
        })}
        {datasets.map((dataset, datasetIndex) => {
          const data = getCompareSeriesData(dataset);
          const path = labels
            .map((_, index) => {
              const p = point(index, data[index]);
              return `${index === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
            })
            .join(" ") + " Z";
          return (
            <g key={dataset.label || dataset.company_name || datasetIndex} style={{ "--series-color": COMPARE_COLORS[datasetIndex % COMPARE_COLORS.length] }}>
              <path className="compare-radar-area" d={path} />
              <path className="compare-radar-line" d={path} />
            </g>
          );
        })}
      </svg>
      <div className="compare-chart-legend">
        {datasets.map((dataset, index) => (
          <span key={dataset.label || dataset.company_name || index} className="legend-chip">
            <i className="legend-swatch" style={{ background: COMPARE_COLORS[index % COMPARE_COLORS.length] }} />
            {dataset.label || dataset.company_name || `#${index + 1}`}
          </span>
        ))}
      </div>
    </div>
  );
}

function CompareBarChart({ chart, language }) {
  const axis = Array.isArray(chart?.x) ? chart.x : [];
  const series = Array.isArray(chart?.series) ? chart.series : [];
  const values = series.flatMap((item) => getCompareSeriesData(item).map((value) => Math.abs(Number(value))).filter(Number.isFinite));
  const max = Math.max(1, ...values);

  if (!axis.length || !series.length) {
    return <div className="compare-chart-empty">{ct(language, "noData")}</div>;
  }

  return (
    <div className="compare-bars">
      {axis.map((item, rowIndex) => (
        <div key={`${getCompareAxisLabel(item)}-${rowIndex}`} className="compare-bar-company">
          <div className="compare-bar-company-name">{getCompareAxisLabel(item)}</div>
          <div className="compare-bar-series">
            {series.map((serie, serieIndex) => {
              const raw = getCompareSeriesData(serie)[rowIndex];
              const num = Number(raw);
              const isFiniteValue = Number.isFinite(num);
              const width = isFiniteValue ? Math.max(4, (Math.abs(num) / max) * 100) : 0;
              return (
                <div key={`${serie.key || serie.label}-${rowIndex}`} className="compare-bar-row">
                  <span>{serie.label || serie.key}</span>
                  <div className="compare-bar-track">
                    <i
                      className={isFiniteValue && num < 0 ? "is-negative" : ""}
                      style={{ width: `${width}%`, background: COMPARE_COLORS[serieIndex % COMPARE_COLORS.length] }}
                    />
                  </div>
                  <strong>{formatCompareValue(raw, language)}</strong>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function CompareChartCard({ chart, language }) {
  if (!chart) return null;
  const isRadar = chart.type === "radar";
  return (
    <article className={`chart-card compare-chart-card compare-chart-${chart.type || "bar"}`}>
      <div className="chart-head">
        <div>
          <div className="panel-label">{ct(language, "charts")}</div>
          <h3>{chart.title || ct(language, "charts")}</h3>
        </div>
        <span className="status-badge muted">{isRadar ? "0-100" : chart.type || "chart"}</span>
      </div>
      {isRadar ? <CompareRadarChart chart={chart} language={language} /> : <CompareBarChart chart={chart} language={language} />}
    </article>
  );
}

function compareCellSortValue(raw) {
  const v = raw && typeof raw === "object" ? (raw.normalized ?? raw.value ?? raw.raw) : raw;
  if (typeof v === "number") return { num: v, str: String(v) };
  const n = parseFloat(String(v ?? "").replace(/[^\d.\-]/g, ""));
  return { num: Number.isFinite(n) ? n : null, str: String(v ?? "") };
}

function CompareTable({ table, title, language }) {
  const columns = Array.isArray(table?.columns) ? table.columns : [];
  const rows = Array.isArray(table?.rows) ? table.rows : [];
  const [sort, setSort] = React.useState({ key: null, dir: 1 });
  const [transposed, setTransposed] = React.useState(false);

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }));
  const sortedRows = React.useMemo(() => {
    if (!sort.key) return rows;
    return [...rows].sort((a, b) => {
      const av = compareCellSortValue(a[sort.key]);
      const bv = compareCellSortValue(b[sort.key]);
      if (av.num !== null && bv.num !== null) return (av.num - bv.num) * sort.dir;
      if (av.num !== null) return -1;
      if (bv.num !== null) return 1;
      return av.str.localeCompare(bv.str) * sort.dir;
    });
  }, [rows, sort]);

  // "Среднее по сравнению" row — averages each numeric metric across the compared issuers (ТЗ §3.6).
  const avgRow = React.useMemo(() => {
    const out = {};
    let hasAny = false;
    columns.forEach((column) => {
      const nums = rows.map((r) => compareCellSortValue(r[column.key]).num).filter((n) => n !== null);
      if (nums.length >= 2) {
        out[column.key] = nums.reduce((a, b) => a + b, 0) / nums.length;
        hasAny = true;
      } else {
        out[column.key] = null;
      }
    });
    return hasAny ? out : null;
  }, [rows, columns]);

  // Rules of Hooks: the empty-table bail-out MUST come after every hook call.
  // When it sat above the two useMemo above, a table going empty -> non-empty
  // rendered a different number of hooks than the previous pass, which React
  // treats as a fatal error — it threw and blanked the whole compare view.
  if (!columns.length || !rows.length) return null;

  const avgLabel = language === "en" ? "Average" : language === "uz" ? "O'rtacha" : "Среднее";
  const labelCol = columns[0];
  const metricCols = columns.slice(1);
  const transposeLabel = language === "en" ? "Transpose" : language === "uz" ? "Transpoze" : "Транспонировать";
  const rowHeader = (row, i) => {
    const c = labelCol ? formatCompareCell(row[labelCol.key], labelCol, language).value : null;
    return c || row.company_name || row.ticker || `#${i + 1}`;
  };

  return (
    <article className="compare-table-card">
      <div className="section-title-row">
        <h3>{title}</h3>
        <div className="compare-table-tools">
          <button type="button" className="ghost-btn compare-transpose-btn" onClick={() => setTransposed((v) => !v)}>
            ⇄ {transposeLabel}
          </button>
          <span className="muted">{rows.length}</span>
        </div>
      </div>
      <div className="compare-table-scroll">
        {!transposed ? (
          <table className="compare-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key} className="compare-th-sortable" onClick={() => toggleSort(column.key)}>
                    {column.label || column.key}
                    {sort.key === column.key ? <span className="compare-sort-arrow">{sort.dir === 1 ? " ▲" : " ▼"}</span> : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row, rowIndex) => (
                <tr key={`${title}-${row.company_name || row.ticker || rowIndex}`}>
                  {columns.map((column) => {
                    const cell = formatCompareCell(row[column.key], column, language);
                    return (
                      <td key={column.key}>
                        <strong>{cell.value}</strong>
                        {cell.normalized !== null && cell.normalized !== undefined ? (
                          <span>{ct(language, "normalized")}: {formatCompareValue(cell.normalized, language, "/100")}</span>
                        ) : null}
                        {cell.rank ? <em>#{cell.rank}</em> : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {avgRow && (
                <tr className="compare-avg-row">
                  {columns.map((column, ci) => (
                    <td key={column.key}>
                      {ci === 0 ? (
                        <strong>{avgLabel}</strong>
                      ) : avgRow[column.key] !== null ? (
                        <strong>{formatCompareValue(avgRow[column.key], language, "")}</strong>
                      ) : (
                        <span>—</span>
                      )}
                    </td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        ) : (
          <table className="compare-table">
            <thead>
              <tr>
                <th>{labelCol?.label || ""}</th>
                {sortedRows.map((row, i) => (
                  <th key={i}>{rowHeader(row, i)}</th>
                ))}
                {avgRow && <th className="compare-avg-col">{avgLabel}</th>}
              </tr>
            </thead>
            <tbody>
              {metricCols.map((column) => (
                <tr key={column.key}>
                  <td><strong>{column.label || column.key}</strong></td>
                  {sortedRows.map((row, i) => {
                    const cell = formatCompareCell(row[column.key], column, language);
                    return (
                      <td key={i}>
                        <strong>{cell.value}</strong>
                        {cell.rank ? <em>#{cell.rank}</em> : null}
                      </td>
                    );
                  })}
                  {avgRow && (
                    <td className="compare-avg-col">
                      {avgRow[column.key] !== null && avgRow[column.key] !== undefined
                        ? <strong>{formatCompareValue(avgRow[column.key], language, "")}</strong>
                        : <span>—</span>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </article>
  );
}

function CompareSummaryText({ summary, language }) {
  const text = summary?.text || summary?.summary || "";
  if (!text) {
    return <p className="empty-copy">{summary?.error || ct(language, "noData")}</p>;
  }
  return (
    <div className="compare-ai-text">
      {String(text)
        .split(/\n+/)
        .filter(Boolean)
        .map((line, index) => (
          <p key={index}>{line}</p>
        ))}
    </div>
  );
}

export { CompareChartCard, CompareLeaderCards, CompareRanking, CompareSummaryText, CompareTable, compareTableTitle };
