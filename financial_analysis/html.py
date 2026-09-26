"""Render completed analytical results as standalone HTML."""
from __future__ import annotations

from datetime import datetime
import financial_analysis.sections as financial_analysis_sections
import re


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Анализ финансовой отчётности — {company}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;0,8..60,600;1,8..60,300;1,8..60,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #1a1612;
    --ink-mid: #3d3530;
    --ink-light: #6b5e55;
    --rule: #c9b99a;
    --rule-light: #e8ddd0;
    --accent: #8b1a1a;
    --accent-soft: #c0392b;
    --gold: #9a7b3a;
    --bg: #faf7f2;
    --bg-warm: #f3ede3;
    --bg-table: #fdf9f4;
    --green: #1a5c2e;
    --red: #8b1a1a;
    --amber: #7a5200;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--ink); font-family: 'Source Serif 4', Georgia, serif; font-size: 17px; line-height: 1.8; }}

  .masthead {{ border-top: 3px solid var(--ink); border-bottom: 1px solid var(--rule); padding: 12px 0 8px; text-align: center; background: var(--bg); margin-bottom: 0; }}
  .masthead-journal {{ font-family: 'Playfair Display', serif; font-size: 11px; letter-spacing: 0.3em; text-transform: uppercase; color: var(--ink-light); }}
  .masthead-title {{ font-family: 'Playfair Display', serif; font-size: 28px; font-weight: 700; letter-spacing: 0.01em; color: var(--ink); margin: 6px 0 4px; }}
  .masthead-sub {{ font-size: 13px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--gold); }}
  .masthead-rule {{ display: flex; align-items: center; gap: 12px; margin: 10px auto 0; max-width: 400px; justify-content: center; }}
  .masthead-rule span {{ height: 1px; flex: 1; background: var(--rule); }}
  .masthead-rule em {{ font-size: 11px; color: var(--ink-light); letter-spacing: 0.2em; font-style: normal; }}

  .page {{ max-width: 900px; margin: 0 auto; padding: 0 40px 80px; }}
  .meta-bar {{ border-bottom: 2px solid var(--ink); padding: 14px 0; display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; margin-bottom: 40px; }}
  .meta-item {{ padding: 0 16px; border-right: 1px solid var(--rule); }}
  .meta-item:first-child {{ padding-left: 0; }}
  .meta-item:last-child {{ border-right: none; }}
  .meta-label {{ font-size: 9px; letter-spacing: 0.3em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 2px; }}
  .meta-value {{ font-family: 'Playfair Display', serif; font-size: 13px; color: var(--ink); }}

  .abstract {{ border-left: 3px solid var(--accent); padding: 20px 24px; background: var(--bg-warm); margin-bottom: 44px; position: relative; }}
  .abstract::before {{ content: 'АННОТАЦИЯ'; font-size: 9px; letter-spacing: 0.35em; color: var(--accent); display: block; margin-bottom: 10px; }}
  .abstract p {{ font-size: 15px; line-height: 1.75; color: var(--ink-mid); font-style: italic; }}

  .section {{ margin-bottom: 52px; }}
  .section-number {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--gold); letter-spacing: 0.1em; display: block; margin-bottom: 4px; }}
  h2 {{ font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 700; color: var(--ink); border-bottom: 2px solid var(--ink); padding-bottom: 8px; margin-bottom: 22px; line-height: 1.3; }}
  h3 {{ font-family: 'Playfair Display', serif; font-size: 16px; font-weight: 600; font-style: italic; color: var(--accent); margin: 28px 0 12px; }}
  p {{ margin-bottom: 16px; text-align: justify; hyphens: auto; }}
  p:last-child {{ margin-bottom: 0; }}
  .dropcap::first-letter {{ font-family: 'Playfair Display', serif; font-size: 68px; font-weight: 700; float: left; line-height: 0.8; margin: 6px 8px -4px 0; color: var(--accent); }}
  .prose {{ font-size: 15px; line-height: 1.85; white-space: pre-wrap; }}

  .table-wrap {{ margin: 28px 0 32px; overflow-x: auto; }}
  .table-caption {{ font-size: 11px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 8px; padding-left: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; background: var(--bg-table); }}
  thead tr {{ background: var(--ink); color: #f5ede0; }}
  thead th {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; padding: 10px 12px; text-align: right; font-weight: 500; }}
  thead th:first-child {{ text-align: left; }}
  tbody tr {{ border-bottom: 1px solid var(--rule-light); }}
  tbody tr:hover {{ background: #f0e9de; }}
  tbody tr.subtotal {{ background: #ede4d6; font-weight: 600; }}
  tbody tr.total {{ background: var(--bg-warm); border-top: 2px solid var(--rule); border-bottom: 2px solid var(--rule); font-weight: 700; }}
  tbody tr.section-head {{ background: #f7f1e8; }}
  tbody td {{ padding: 8px 12px; color: var(--ink-mid); vertical-align: middle; }}
  tbody td:first-child {{ color: var(--ink); }}
  tbody td.num {{ text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 13px; }}
  .pos {{ color: var(--green); font-weight: 600; }}
  .neg {{ color: var(--red); font-weight: 600; }}
  .warn {{ color: var(--amber); font-weight: 600; }}
  .indent {{ padding-left: 28px !important; font-size: 13.5px; color: var(--ink-light); }}

  .callout-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 24px 0 32px; }}
  .callout {{ border: 1px solid var(--rule); padding: 16px 20px; background: var(--bg-warm); }}
  .callout.good {{ border-left: 4px solid var(--green); }}
  .callout.bad {{ border-left: 4px solid var(--red); }}
  .callout.neutral {{ border-left: 4px solid var(--gold); }}
  .callout-label {{ font-size: 9px; letter-spacing: 0.3em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 6px; }}
  .callout-value {{ font-family: 'Playfair Display', serif; font-size: 26px; font-weight: 700; color: var(--ink); }}
  .callout-desc {{ font-size: 12.5px; color: var(--ink-light); margin-top: 4px; line-height: 1.5; }}

  .kpi-row {{ display: flex; gap: 0; border: 1px solid var(--rule); margin: 24px 0 32px; }}
  .kpi-item {{ flex: 1; padding: 16px 18px; border-right: 1px solid var(--rule); text-align: center; }}
  .kpi-item:last-child {{ border-right: none; }}
  .kpi-label {{ font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 6px; }}
  .kpi-val {{ font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 700; color: var(--accent); }}
  .kpi-sub {{ font-size: 11px; color: var(--ink-light); margin-top: 2px; }}

  .formula-box {{ border: 1px solid var(--rule); border-left: 3px solid var(--gold); background: #faf5ec; padding: 12px 18px; font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--ink-mid); margin: 12px 0 20px; }}

  .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 20px 0; }}
  .metric-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 16px; }}
  .metric-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.15em; color: var(--ink-light); margin-bottom: 8px; }}
  .metric-val {{ font-family: 'Playfair Display', serif; font-size: 24px; margin-bottom: 4px; }}
  .metric-sub {{ font-size: 12px; color: var(--ink-light); line-height: 1.4; }}
  .val-green {{ color: var(--green); }} .val-red {{ color: var(--red); }} .val-yellow {{ color: var(--amber); }}

  .swot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 20px 0; }}
  @media (max-width: 600px) {{ .swot-grid {{ grid-template-columns: 1fr; }} }}
  .swot-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 18px; }}
  .swot-card h3 {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.15em; margin-bottom: 12px; border: none; padding: 0; }}
  .swot-card.strengths h3 {{ color: var(--green); }} .swot-card.weaknesses h3 {{ color: var(--red); }}
  .swot-item {{ margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--rule-light); }}
  .swot-item:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
  .swot-fact {{ font-size: 14px; font-weight: 500; }} .swot-num {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--accent); }} .swot-sig {{ font-size: 12px; color: var(--ink-light); margin-top: 2px; }}

  .catalyst-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 20px 0; }}
  @media (max-width: 600px) {{ .catalyst-grid {{ grid-template-columns: 1fr; }} }}
  .catalyst-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 14px; }}
  .catalyst-card.up {{ border-left: 4px solid var(--green); }}
  .catalyst-card.down {{ border-left: 4px solid var(--red); }}
  .catalyst-card.macro {{ border-left: 4px solid var(--amber); }}
  .catalyst-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }}
  .catalyst-label.up {{ color: var(--green); }} .catalyst-label.down {{ color: var(--red); }} .catalyst-label.macro {{ color: var(--amber); }}
  .catalyst-item {{ font-size: 13px; color: var(--ink); margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid var(--rule-light); }}
  .catalyst-item:last-child {{ border-bottom: none; margin-bottom: 0; padding-bottom: 0; }}

  .forecast-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0; }}
  @media (max-width: 600px) {{ .forecast-grid {{ grid-template-columns: 1fr; }} }}
  .forecast-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 18px; text-align: center; }}
  .forecast-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.15em; color: var(--ink-light); margin-bottom: 8px; }}
  .forecast-val {{ font-family: 'Playfair Display', serif; font-size: 18px; margin-bottom: 6px; }}
  .forecast-note {{ font-size: 12px; color: var(--ink-light); line-height: 1.4; }}
  .trend-up {{ color: var(--green); }} .trend-down {{ color: var(--red); }} .trend-flat {{ color: var(--amber); }}

  .tips-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 22px; margin: 20px 0; }}
  .tips-row {{ display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }}
  .tips-badge {{ background: rgba(154, 123, 58, 0.1); border: 1px solid rgba(154, 123, 58, 0.3); color: var(--gold); font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 5px 12px; }}
  .watch-item {{ display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--rule-light); }}
  .watch-item:last-child {{ border-bottom: none; }}
  .watch-num {{ width: 22px; height: 22px; background: var(--gold); color: var(--bg); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 500; flex-shrink: 0; margin-top: 2px; }}
  .watch-name {{ font-size: 14px; font-weight: 500; }} .watch-why {{ font-size: 12px; color: var(--ink-light); }}

  .trend-row {{ display: flex; flex-direction: column; gap: 8px; margin: 20px 0; }}
  .trend-item {{ display: flex; align-items: center; gap: 10px; background: var(--bg-warm); border: 1px solid var(--rule); padding: 10px 14px; }}
  .trend-name {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--ink-light); width: 90px; flex-shrink: 0; }}
  .trend-bar-wrap {{ flex: 1; height: 4px; background: var(--rule-light); overflow: hidden; }}
  .trend-bar {{ height: 4px; }}
  .trend-bar.pos {{ background: var(--green); }} .trend-bar.neg {{ background: var(--red); }} .trend-bar.neu {{ background: var(--amber); }}
  .trend-val {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--gold); width: 55px; text-align: right; flex-shrink: 0; }}
  .trend-lbl {{ font-size: 12px; color: var(--ink-light); margin-left: 4px; flex-shrink: 0; }}

  .verdict {{ background: var(--ink); color: #f5ede0; padding: 32px 36px; margin: 40px 0 0; }}
  .verdict-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.3em; color: var(--gold); margin-bottom: 14px; }}
  .verdict h3 {{ color: #f5ede0; font-family: 'Playfair Display', serif; font-size: 20px; margin: 0 0 16px; font-style: normal; border: none; padding: 0; }}
  .verdict p {{ color: #d4c5b0; font-size: 15px; margin-bottom: 12px; text-align: left; }}
  .verdict ul {{ list-style: none; padding: 0; margin-top: 8px; }}
  .verdict ul li {{ font-size: 14.5px; color: #d4c5b0; padding: 5px 0 5px 18px; position: relative; border-bottom: 1px solid #3d352a; }}
  .verdict ul li::before {{ content: '›'; position: absolute; left: 0; color: var(--gold); font-size: 18px; line-height: 1.4; }}

  .web-toggle {{ background: none; border: 1px solid var(--rule); color: var(--ink-light); font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 6px 14px; cursor: pointer; text-transform: uppercase; letter-spacing: 0.1em; margin: 10px 0; }}
  .web-toggle:hover {{ border-color: var(--gold); color: var(--gold); }}
  .web-text {{ font-size: 13px; color: var(--ink-light); background: var(--bg-warm); border: 1px solid var(--rule); border-left: 3px solid var(--gold); padding: 16px 20px; line-height: 1.75; white-space: pre-wrap; max-height: 240px; overflow-y: auto; display: none; margin-top: 10px; }}

  .footer {{ border-top: 2px solid var(--ink); padding: 20px 0 0; margin-top: 60px; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; font-size: 12px; color: var(--ink-light); }}
  .footer strong {{ display: block; color: var(--ink); margin-bottom: 4px; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; }}

  @media (max-width: 700px) {{
    .page {{ padding: 0 20px 60px; }}
    .meta-bar {{ grid-template-columns: 1fr 1fr; }}
    .callout-grid {{ grid-template-columns: 1fr; }}
    .kpi-row {{ flex-wrap: wrap; }}
    .footer {{ grid-template-columns: 1fr; }}
    .masthead-title {{ font-size: 20px; }}
  }}

  @media print {{
    body {{ font-size: 12pt; }}
    .page {{ max-width: 100%; padding: 0; }}
    h2 {{ page-break-after: avoid; }}
    .section {{ page-break-inside: avoid; }}
    table {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>

<div class="masthead">
  <div class="masthead-journal">Финансовый анализ / Financial Analysis Report</div>
  <div class="masthead-title">{company}</div>
  <div class="masthead-sub">Анализ финансовой отчётности — {annual_period}</div>
  <div class="masthead-rule"><span></span><em>{analyzed_at}</em><span></span></div>
</div>

<div class="page">

  <div class="meta-bar">
    <div class="meta-item">
      <div class="meta-label">Эмитент</div>
      <div class="meta-value">{company}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Период</div>
      <div class="meta-value">{annual_period}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Кварталы</div>
      <div class="meta-value">{quarterly_period}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Скоринг</div>
      <div class="meta-value">{score}/100 · {score_grade}</div>
    </div>
  </div>

  <div class="abstract">
    <p>{company_profile}</p>
  </div>

  <!-- РАЗДЕЛ 1: ПРОФИЛЬ И МЕТОДОЛОГИЯ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 1</span>
    <h2>Профиль компании и методология анализа</h2>
    <p class="dropcap">{score_desc}</p>
    <p>Настоящий анализ строится на трёх классических методах финансового анализа: <strong>горизонтальный анализ</strong> (оценка динамики абсолютных и относительных изменений), <strong>вертикальный анализ</strong> (структурный анализ — удельный вес каждой статьи) и <strong>коэффициентный анализ</strong> (расчёт показателей по группам: ликвидность, рентабельность, качество активов, достаточность капитала, эффективность).</p>
  </div>

  <!-- РАЗДЕЛ 2: ФИНАНСОВЫЙ АНАЛИЗ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 2</span>
    <h2>Анализ финансовых показателей</h2>
    <div class="prose">{what_money}</div>
    {trends_html}
    <div class="prose" style="margin-top:20px">{trend_text}</div>
  </div>

  <!-- РАЗДЕЛ 3: ЭКСПЕРТНЫЕ МЕТРИКИ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 3</span>
    <h2>Экспертные метрики и индикаторы</h2>
    <p>Ключевые метрики рассчитаны по методологиям Piotroski F-Score, Altman Z-Score, критериям Баффетта и другим признанным подходам.</p>
    <div class="metrics-grid">{metrics_html}</div>
    <h3>Ликвидность акции на рынке</h3>
    {liquidity_html}
  </div>

  <!-- РАЗДЕЛ 4: ТЕХНИЧЕСКИЙ АНАЛИЗ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 4</span>
    <h2>Технический анализ и уровни Фибоначчи</h2>
    <div class="prose">{fibonacci_text}</div>
    <h3>Оценка стоимости акции</h3>
    <div class="prose">{price_valuation}</div>
  </div>

  <!-- РАЗДЕЛ 5: КАТАЛИЗАТОРЫ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 5</span>
    <h2>Факторы, влияющие на стоимость</h2>
    {catalysts_html}
  </div>

  <!-- РАЗДЕЛ 6: СИЛЬНЫЕ И СЛАБЫЕ СТОРОНЫ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 6</span>
    <h2>Сильные и слабые стороны компании</h2>
    <div class="swot-grid">
      <div class="swot-card strengths"><h3>Сильные стороны</h3>{strengths_html}</div>
      <div class="swot-card weaknesses"><h3>Риски и слабости</h3>{weaknesses_html}</div>
    </div>
  </div>

  <!-- РАЗДЕЛ 7: ВЕРДИКТ И РЕКОМЕНДАЦИИ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 7</span>
    <h2>Инвестиционный вердикт</h2>

    <h3>Прогноз</h3>
    <div class="forecast-grid">{forecast_html}</div>

    <h3>Рекомендации</h3>
    <div class="tips-card">
      <div class="tips-row">{tips_badges_html}</div>
      <div>{watch_html}</div>
    </div>

    <div class="verdict">
      <div class="verdict-label">{verdict_emoji} ЗАКЛЮЧЕНИЕ</div>
      <h3>{verdict_label}</h3>
      <p>{verdict_text}</p>
      <p>{itog}</p>
    </div>
  </div>

  <!-- ВЕБ-ИССЛЕДОВАНИЕ -->
  <div class="section">
    <span class="section-number">ПРИЛОЖЕНИЕ</span>
    <h2>Источники и веб-исследование</h2>
    <button class="web-toggle" onclick="var d=this.nextElementSibling;d.style.display=d.style.display==='block'?'none':'block'">Показать источники</button>
    <div class="web-text">{web_research}</div>
  </div>

  <div class="footer">
    <div>
      <strong>Методология</strong>
      Fibonacci · Piotroski · Graham · Altman
    </div>
    <div>
      <strong>Дисклеймер</strong>
      Данный отчёт не является инвестиционной рекомендацией
    </div>
  </div>

</div>
</body>
</html>
"""


def build_metrics_html(metrics: dict) -> str:
    html = ""

    # Piotroski
    if "piotroski_f_score" in metrics:
        p = metrics["piotroski_f_score"]
        score = p["score"]
        css = "val-green" if score >= 7 else "val-yellow" if score >= 4 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Piotroski F-Score</div>
            <div class="metric-val {css}">{score}/9</div>
            <div class="metric-sub">{p["verdict"]}</div>
        </div>'''

    # Altman Z
    if "altman_z_score" in metrics:
        a = metrics["altman_z_score"]
        z = a["score"]
        css = "val-green" if z > 2.99 else "val-yellow" if z > 1.81 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Altman Z-Score</div>
            <div class="metric-val {css}">{z}</div>
            <div class="metric-sub">{a["zone"]}</div>
        </div>'''

    # Buffett
    if "buffett_criteria" in metrics:
        b = metrics["buffett_criteria"]
        passed = b["passed"]
        total  = b["total"]
        css = "val-green" if passed >= 4 else "val-yellow" if passed >= 2 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Критерии Баффетта</div>
            <div class="metric-val {css}">{passed}/{total}</div>
            <div class="metric-sub">{b["verdict"]}</div>
        </div>'''

    # Momentum
    if "momentum" in metrics:
        mo = metrics["momentum"]
        css_map = {"bullish": "val-green", "bearish": "val-red", "neutral": "val-yellow"}
        css = css_map.get(mo.get("css","neutral"), "val-yellow")
        streak = mo.get("growth_streak", 0)
        streak_txt = f"{streak} кв. роста подряд" if streak > 0 else (
            f"{mo.get('decline_streak',0)} кв. падения" if mo.get('decline_streak',0) > 0 else "")
        h3m = mo.get("horizons",{}).get("3m",{})
        val_str = f"{h3m.get('revenue_pct',0):+.1f}%" if h3m.get("revenue_pct") is not None else "—"
        html += f'''<div class="metric-card">
            <div class="metric-label">Momentum (3м выручка)</div>
            <div class="metric-val {css}">{val_str}</div>
            <div class="metric-sub">{mo.get("overall","")[:60]}<br>{streak_txt}</div>
        </div>'''

    # Industry comparison
    if "industry" in metrics:
        ind = metrics["industry"]
        grade = ind.get("grade","inperform")
        css_map = {"outperform":"val-green","inperform":"val-yellow","underperform":"val-red"}
        css = css_map.get(grade, "val-yellow")
        label_map = {"outperform":"Выше рынка","inperform":"На уровне рынка","underperform":"Ниже рынка"}
        label = label_map.get(grade, grade)
        good = ind.get("good_count",0); ok = ind.get("ok_count",0); weak = ind.get("weak_count",0)
        sector = ind.get("sector_name","")[:25]
        html += f'''<div class="metric-card">
            <div class="metric-label">Отраслевой бенчмарк</div>
            <div class="metric-val {css}">{label}</div>
            <div class="metric-sub">{sector}<br>✅{good} / 🟡{ok} / ❌{weak} показателей</div>
        </div>'''

    # DCF
    if "dcf" in metrics:
        d = metrics["dcf"]
        val_bn = d.get("intrinsic_value_bn")
        sig = d.get("signal", "neutral")
        css = "val-green" if sig == "bullish" else "val-red" if sig == "bearish" else "val-yellow"
        val_str = f"{val_bn} млрд" if val_bn else "н/д"
        html += f'''<div class="metric-card">
            <div class="metric-label">DCF — справедливая стоимость</div>
            <div class="metric-val {css}">{val_str}</div>
            <div class="metric-sub">{d.get("verdict", "")[:80]}</div>
        </div>'''

    # Total score
    if "total_score" in metrics:
        t = metrics["total_score"]
        s = t["score"]
        css = "val-green" if s >= 70 else "val-yellow" if s >= 45 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Итоговый скоринг</div>
            <div class="metric-val {css}">{s}/100</div>
            <div class="metric-sub">{t["grade"]}</div>
        </div>'''

    return html or "<div class='metric-sub'>Метрики не рассчитаны</div>"


def build_liquidity_html(metrics: dict) -> str:
    liquidity = (metrics or {}).get("market_liquidity")
    if not liquidity:
        return "<div class='prose-plain'>Нет данных по биржевой ликвидности за последние 30 дней.</div>"

    label = str(liquidity.get("liquidity_label", "")).lower()
    label_map = {
        "high": ("Высокая", "val-green"),
        "medium": ("Средняя", "val-yellow"),
        "low": ("Низкая", "val-red"),
    }
    label_text, label_css = label_map.get(label, ("Нет данных", "val-yellow"))

    trade_days = liquidity.get("trade_days", "—")
    trade_count = liquidity.get("trade_count", "—")
    avg_trade_value = liquidity.get("avg_trade_value", "—")
    total_volume = liquidity.get("total_volume", "—")
    active_days_share = liquidity.get("active_days_share")

    if isinstance(active_days_share, (int, float)):
        active_days_share_text = f"{active_days_share * 100:.0f}%"
    else:
        active_days_share_text = "—"

    if label == "high":
        comment = "Бумага торгуется регулярно. Вход и выход из позиции обычно проще, чем у большинства акций на рынке UZSE."
    elif label == "medium":
        comment = "Ликвидность рабочая, но не идеальная. Крупную позицию лучше набирать постепенно и не рассчитывать на мгновенный выход."
    else:
        comment = "Ликвидность слабая. Даже при хороших финансах акция может быть неудобной для покупки и особенно для продажи."

    def fmt_money(value):
        if isinstance(value, (int, float)):
            return f"{value:,.0f} UZS"
        return "—"

    cards = f"""
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-label">Режим ликвидности</div>
        <div class="metric-val {label_css}">{label_text}</div>
        <div class="metric-sub">Оценка по активности торгов за 30 дней</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Торговых дней</div>
        <div class="metric-val">{trade_days}</div>
        <div class="metric-sub">Из 30 календарных дней</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Сделок</div>
        <div class="metric-val">{trade_count}</div>
        <div class="metric-sub">Количество сделок за период</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Средняя сделка</div>
        <div class="metric-val">{fmt_money(avg_trade_value)}</div>
        <div class="metric-sub">Средний денежный объём одной сделки</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Оборот</div>
        <div class="metric-val">{fmt_money(total_volume)}</div>
        <div class="metric-sub">Суммарный объём торгов за месяц</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Активность</div>
        <div class="metric-val">{active_days_share_text}</div>
        <div class="metric-sub">Доля дней, когда бумага реально торговалась</div>
      </div>
    </div>
    <div class="prose">{comment}</div>
    """
    return cards


def build_trends_html(metrics: dict) -> str:
    """Строит визуальные карточки трендов из metrics["trends"]."""
    if "trends" not in metrics:
        return ""

    t = metrics["trends"]
    html = '<div class="trend-row">'

    def trend_card(name: str, slope: float, label: str, consistency: float = None, acceleration: float = None):
        # Нормализуем slope в ширину бара (0–100%)
        bar_pct = min(100, abs(slope) * 3)
        css = "pos" if slope > 2 else "neg" if slope < -2 else "neu"
        arrow = "↑" if slope > 2 else "↓" if slope < -2 else "→"
        slope_str = f"{arrow} {abs(slope):.1f}%"

        extras = ""
        if acceleration is not None:
            accel_icon = "⚡" if acceleration > 3 else "🐌" if acceleration < -3 else ""
            if accel_icon:
                extras += f' {accel_icon}'
        if consistency is not None:
            cons_str = f"стаб. {consistency:.0f}%"
            extras += f' · {cons_str}'

        return (
            f'<div class="trend-item">'
            f'<span class="trend-name">{name}</span>'
            f'<div class="trend-bar-wrap"><div class="trend-bar {css}" style="width:{bar_pct}%"></div></div>'
            f'<span class="trend-val">{slope_str}</span>'
            f'<span class="trend-lbl">{extras}</span>'
            f'</div>'
        )

    # Выручка
    rv = t.get("revenue", {})
    if rv:
        html += trend_card(
            "Выручка", rv.get("slope", 0), rv.get("label", ""),
            rv.get("consistency"), rv.get("acceleration")
        )

    # Прибыль
    pr = t.get("profit", {})
    if pr:
        html += trend_card(
            "Прибыль", pr.get("slope", 0), pr.get("label", ""),
            pr.get("consistency"), pr.get("acceleration")
        )

    # Маржа
    mg = t.get("margin", {})
    if mg:
        html += trend_card(
            "Маржа", mg.get("slope", 0), mg.get("label", ""),
            mg.get("consistency")
        )

    # Долг (инвертируем — снижение долга это хорошо)
    db = t.get("debt", {})
    if db:
        slope = db.get("slope", 0)
        html += trend_card("Долг", slope, db.get("direction", ""))

    # Общий итог
    overall = t.get("overall_label", "")
    overall_score = t.get("overall_score", 0)
    css_overall = "pos" if overall == "Позитивный" else "neg" if overall == "Негативный" else "neu"
    html += (
        f'<div class="trend-item" style="margin-top:4px;border-color:var(--accent)">'
        f'<span class="trend-name" style="color:var(--accent)">Итог тренда</span>'
        f'<div class="trend-bar-wrap"><div class="trend-bar {css_overall}" style="width:{overall_score/12*100:.0f}%"></div></div>'
        f'<span class="trend-val">{overall_score}/12</span>'
        f'<span class="trend-lbl" style="color:var(--text)">{overall}</span>'
        f'</div>'
    )

    html += '</div>'
    return html


def swot_items_html(text: str) -> str:
    html = ""
    for line in text.splitlines():
        if not line.strip().startswith("•"):
            continue
        p = financial_analysis_sections.parse_bullet(line)
        fact = p.get("Факт", p.get("факт", ""))
        num  = p.get("Цифра", p.get("цифра", ""))
        sig  = p.get("Значимость", p.get("значимость", ""))
        html += f'<div class="swot-item"><div class="swot-fact">{fact}</div><div class="swot-num">{num}</div><div class="swot-sig">{sig}</div></div>'
    return html or "<div class='swot-sig'>Нет данных</div>"


def build_catalysts_html(text: str) -> str:
    up_items, down_items, macro_items = [], [], []
    current = None
    for line in text.splitlines():
        ls = line.strip()
        low = ls.lower()
        if "поднять" in low or "вверх" in low or "рост" in low and "событи" in low:
            current = "up"
        elif "опустить" in low or "вниз" in low or "риск" in low:
            current = "down"
        elif "макро" in low:
            current = "macro"
        elif ls.startswith("•") and current:
            item = ls.lstrip("• ").strip()
            if current == "up":   up_items.append(item)
            elif current == "down": down_items.append(item)
            elif current == "macro": macro_items.append(item)

    def make_card(items, cls, label):
        if not items:
            return ""
        items_html = "".join(f'<div class="catalyst-item">{i}</div>' for i in items[:3])
        return f'<div class="catalyst-card {cls}"><div class="catalyst-label {cls}">{label}</div>{items_html}</div>'

    cards = (
        make_card(up_items,    "up",    "📈 Могут поднять цену") +
        make_card(down_items,  "down",  "📉 Могут опустить цену") +
        make_card(macro_items, "macro", "🌍 Макро-факторы")
    )
    return f'<div class="catalyst-grid">{cards}</div>' if cards else '<div class="prose-plain">Катализаторы не определены</div>'


def build_forecast_html(text: str) -> str:
    """Парсит [ПРОГНОЗ]. Устойчив к любым тире: —, –, -, и переносам строк."""
    import re as _re

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    labels_map = {
        "рост прибыли":      ("Рост прибыли",     ["высокая", "высок"], ["низкая", "низк"]),
        "долговая нагрузка": ("Долговая нагрузка", ["улучшение"],        ["ухудшение"]),
        "ликвидность":       ("Ликвидность",       ["улучшение"],        ["ухудшение"]),
    }

    # Собираем строки по ключам (Claude иногда переносит пояснение)
    merged = {}
    current_key = None
    for line in lines:
        low = line.lower()
        matched = False
        for key in labels_map:
            if low.startswith(key):
                merged[key] = line
                current_key = key
                matched = True
                break
        if not matched and current_key:
            merged[current_key] = merged.get(current_key, "") + " " + line

    cards = []
    for key, (label, good_kw, bad_kw) in labels_map.items():
        if key not in merged:
            continue
        raw = merged[key]
        after_colon = raw.partition(":")[2].strip() if ":" in raw else raw
        # Разбиваем по любому тире
        parts = _re.split(r"\s*[—–\-]\s*", after_colon, maxsplit=1)
        val  = parts[0].strip() if parts else after_colon
        note = parts[1].strip() if len(parts) > 1 else ""
        css = "trend-flat"
        if any(k in val.lower() for k in good_kw):  css = "trend-up"
        elif any(k in val.lower() for k in bad_kw): css = "trend-down"
        cards.append(
            f'<div class="forecast-card">' +
            f'<div class="forecast-label">{label}</div>' +
            f'<div class="forecast-val {css}">{val}</div>' +
            f'<div class="forecast-note">{note}</div>' +
            f'</div>'
        )

    return "\n".join(cards) if cards else "<div class='forecast-card'><div class='forecast-note'>Нет данных</div></div>"


def build_tips_html(text: str):
    badges, watches, watch_n = "", "", 0
    for line in text.splitlines():
        ls = line.strip()
        if ls.lower().startswith("доля"):
            badges += f'<span class="tips-badge">📊 Доля: {ls.partition(":")[2].strip()}</span>'
        elif ls.lower().startswith("горизонт"):
            badges += f'<span class="tips-badge">⏱ {ls.partition(":")[2].strip()}</span>'
        elif re.match(r"^\d+\.", ls):
            watch_n += 1
            rest = re.sub(r"^\d+\.\s*", "", ls)
            p = financial_analysis_sections.parse_bullet("• " + rest.replace("Показатель:", "").strip())
            name = p.get("Показатель", p.get("показатель", rest.split("|")[0].strip()))
            why  = p.get("Почему", p.get("почему", ""))
            watches += f'<div class="watch-item"><div class="watch-num">{watch_n}</div><div><div class="watch-name">{name}</div><div class="watch-why">{why}</div></div></div>'
    return badges, watches


def verdict_parts(text: str):
    """Парсит вердикт. Поддерживает 5 уровней: ПОКУПАТЬ/ДЕРЖАТЬ/НАБЛЮДАТЬ/ОСТОРОЖНО/ВОЗДЕРЖАТЬСЯ."""
    label, body, emoji, css = "Анализ завершён", "", "📋", "yellow"
    for line in text.splitlines():
        ls = line.strip()
        if ls.lower().startswith("метка:"):
            raw = ls.partition(":")[2].strip()
            label = raw
            # 5-уровневая шкала
            if "ПОКУПАТЬ" in raw.upper():
                emoji, css = "🟢", "green"
            elif "ДЕРЖАТЬ" in raw.upper():
                emoji, css = "🟢", "green"
            elif "НАБЛЮДАТЬ" in raw.upper():
                emoji, css = "🟡", "yellow"
            elif "ОСТОРОЖНО" in raw.upper():
                emoji, css = "🟠", "orange"
            elif "ВОЗДЕРЖАТЬСЯ" in raw.upper():
                emoji, css = "🔴", "red"
            # Обратная совместимость со старыми вердиктами
            elif "🟢" in raw:
                emoji, css = "🟢", "green"
            elif "🔴" in raw:
                emoji, css = "🔴", "red"
            else:
                emoji, css = "🟡", "yellow"
        elif ls.lower().startswith("обоснование:"):
            body = ls.partition(":")[2].strip()
    return emoji, label, body, css


def build_html(company_name: str, company_profile: str, web_research: str,
               raw_analysis: str, annual_period: str, quarterly_period: str,
               cost: float, metrics: dict = None) -> str:

    sections = financial_analysis_sections.parse_response(raw_analysis)
    emoji, v_label, v_body, v_css = verdict_parts(sections.get("ВЕРДИКТ", ""))
    fc_html = build_forecast_html(sections.get("ПРОГНОЗ", ""))
    t_badges, t_watches = build_tips_html(sections.get("СОВЕТЫ", ""))
    safe_web = web_research.replace("<", "&lt;").replace(">", "&gt;")

    # Скоринг из секции
    score_text = sections.get("СКОРИНГ", "")
    score_num, score_grade_str, score_desc_str = "—", "—", ""
    for line in score_text.splitlines():
        ls = line.strip()
        if ls.lower().startswith("оценка:"):
            raw = ls.partition(":")[2].strip().split("/")[0].strip()
            score_num = raw
        elif ls.lower().startswith("класс:"):
            score_grade_str = ls.partition(":")[2].strip()
        elif ls.lower().startswith("расшифровка:"):
            score_desc_str = ls.partition(":")[2].strip()

    # Если в секции нет — берём из Python-метрик
    if score_num == "—" and metrics and "total_score" in metrics:
        score_num = str(metrics["total_score"]["score"])
        score_grade_str = metrics["total_score"]["grade"]

    return HTML_TEMPLATE.format(
        company=company_name,
        annual_period=annual_period,
        quarterly_period=quarterly_period,
        cost=cost,
        analyzed_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        score=score_num,
        score_grade=score_grade_str,
        score_desc=score_desc_str,
        company_profile=company_profile,
        web_research=safe_web,
        verdict_class=v_css,
        verdict_emoji=emoji,
        verdict_label=v_label,
        verdict_text=v_body,
        trends_html=build_trends_html(metrics or {}),
        what_money=sections.get("ЧТО_С_ДЕНЬГАМИ", ""),
        trend_text=sections.get("ТРЕНД", ""),
        fibonacci_text=sections.get("ФИБОНАЧЧИ", ""),
        price_valuation=sections.get("ОЦЕНКА_ЦЕНЫ", ""),
        catalysts_html=build_catalysts_html(sections.get("КАТАЛИЗАТОРЫ", "")),
        metrics_html=build_metrics_html(metrics or {}),
        liquidity_html=build_liquidity_html(metrics or {}),
        strengths_html=swot_items_html(sections.get("СИЛЬНЫЕ_СТОРОНЫ", "")),
        weaknesses_html=swot_items_html(sections.get("СЛАБЫЕ_СТОРОНЫ", "")),
        forecast_html=fc_html,
        tips_badges_html=t_badges,
        watch_html=t_watches,
        itog=(
            sections.get("ИТОГ")
            or sections.get("ВЕРДИКТ", "").split("Обоснование:")[-1].strip()
            or "Анализ завершён. Смотри вердикт выше."
        ),
    )
