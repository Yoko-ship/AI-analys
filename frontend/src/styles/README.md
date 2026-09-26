# Shared style composition

`../styles.css` is the single entry point for the shared cascade. Its imports
retain the original declaration order, including the later theme and workspace
overrides. Each file contains complete top-level rules and media queries.

Find the relevant area here:

- Shell, typography and theme: `base`, `design-tokens`, `topbar`,
  `navigation-rates`, `theme-print`, `newspaper-shell`.
- Market: `market-filters-events`, `market-columns`, `market-controls`,
  `market-panel-map`, `market-treemap`.
- Research: `analysis-summary`, `score-content`, `analysis-builder`,
  `analysis-content`, `analysis-report`, `research-workspace`.
- Company, catalogue, news and bonds: `company`, `catalog-notifications`,
  `disclosure-news`, `news-article`, `newsroom`, `audit-bonds`.
- Shared cards, landing and profile: the remaining named sections.

Edit the owning section rather than appending another override to the entry
point. Import order affects specificity ties; avoid reordering or lazy-loading
these files without checking the rendered pages. The separate `theme.css`,
`mobile.css`, `landing.css`, `market.css`, `profile.css` and `auth.css` keep their
existing order in `main.jsx`.

The extraction preserved all 15,322 ordered non-comment syntax nodes from the
current API stylesheet across 33 sections. Future edits should use the browser
regressions for behavior and visual checks; this source comparison is migration
evidence, not a claim that later compiled assets remain identical.
