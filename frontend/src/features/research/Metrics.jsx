import { safeNumber } from "../../shared/format.jsx";
import { scorePercent, scoreTone } from "../../shared/chartModel.jsx";
import { t } from "../../shared/i18n.jsx";

function ScoreGauge({ score, language }) {
  const numeric = safeNumber(score);
  const value = scorePercent(numeric) ?? 0;
  const radius = 48;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (value / 100) * circumference;
  const tone = scoreTone(numeric);

  // Gradient colors based on tone
  const gradientColors = {
    good: ["#10b981", "#059669"],
    warning: ["#f59e0b", "#d97706"],
    danger: ["#ee6a60", "#dc2626"],
    neutral: ["#ff9d00", "#e68a00"],
  };
  const [startColor, endColor] = gradientColors[tone] || gradientColors.neutral;

  return (
    <div className={`score-gauge tone-${tone}`}>
      <svg viewBox="0 0 128 128" role="img" aria-label={t(language, "analysis.score")}>
        <defs>
          <linearGradient id={`scoreGradient-${tone}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={startColor} />
            <stop offset="100%" stopColor={endColor} />
          </linearGradient>
          <filter id="gaugeGlow">
            <feGaussianBlur stdDeviation="2" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <circle className="score-gauge-track" cx="64" cy="64" r={radius} />
        <circle
          className="score-gauge-progress"
          cx="64"
          cy="64"
          r={radius}
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: dashOffset,
            stroke: `url(#scoreGradient-${tone})`,
          }}
          filter="url(#gaugeGlow)"
        />
      </svg>
      <div className="score-gauge-center">
        <strong>{numeric === null ? "--" : Math.round(numeric)}</strong>
        <span>{t(language, "analysis.score")}</span>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, tone = "neutral" }) {
  // Tone indicator icons
  const toneIcons = {
    good: "↑",
    warning: "→",
    danger: "↓",
    neutral: "•",
  };
  const icon = toneIcons[tone] || toneIcons.neutral;

  return (
    <article className={`metric-card metric-${tone} tone-${tone}`}>
      <div className="metric-header">
        <div className="metric-label">{label}</div>
        <span className={`metric-indicator tone-${tone}`}>{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </article>
  );
}

export { MetricCard };
