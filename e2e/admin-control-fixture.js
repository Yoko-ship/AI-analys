// Synthetic QA records. Never imported by the production app.
export function controlFixture(role = "analyst") {
  const doc = { id: "doc-fixture", version: 1, ticker: "UZNF", title: "Interim financial statements · QA fixture", standard: "IFRS", period: "2026H1", period_end: "2026-06-30", duration_months: 6,
    detected_format: "XLSX", detected_mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", checksum: "sample", status: "VALIDATED", source: "openinfo.uz", source_url: "https://openinfo.uz/example", parsed: true, verified: true, used_in_analysis: false, blockers: [], warnings: ["FORMAT_MISMATCH"] };
  const fact = { id: "fact-fixture", version: 1, ticker: "UZNF", title: "Net asset value", metric_code: "NAV", value: 123456, unit: "thousand UZS", period: "2026H1", standard: "IFRS", status: "verified", document_id: doc.id, source_line_id: "Balance!B2", source_location: { sheet: "Balance", cell: "B2" } };
  const calculation = { id: "calc-fixture", version: 1, ticker: "UZNF", metric_code: "price_to_nav", value: 1.14, raw_result: "1.14", display_result: "1.14", unit: "ratio", period: "2026H1", standard: "IFRS", status: "verified", formula_version: "fund-nav-1", expression: "market_price / NAV_per_share", report_period_end: "2026-06-30", market_price_at: "2026-08-28", shares_at: "2026-06-30", sector_template: "investment_fund", inputs: [fact], blockers: [] };
  const incident = { id: "incident-fixture", version: 1, ticker: "UZNF", blocker_code: "PERIOD_CLASSIFICATION_ERROR", status: "OPEN", severity: "P1", stage: "classification", impact_count: 2, affected_ids: [doc.id], sla_due_at: "2026-08-30T20:00:00Z", comments: [], evidence: { document_id: doc.id } };
  const rows = {
    documents: [doc, { ...doc, id: "doc-second", ticker: "HMKB", title: "Quarterly statement", standard: "NSBU", period: "2026Q1" }],
    issuers: [{ id: "UZNF", version: 1, ticker: "UZNF", title: "Uzbekistan National Investment Fund", org_id: "fixture", special_type: "investment_fund", sector_template: "investment_fund", status: "INDEXED" }],
    facts: [fact], calculations: [calculation], incidents: [incident],
    coverage: [{ id: doc.id, version: 1, ticker: "UZNF", period: "2026H1", standard: "IFRS", status: "PUBLISHED_NOT_USED", file_available: true, parsed: true, verified: true, used_in_analysis: false }],
    jobs: [], audit: [], rules: [], publications: [], analyses: [], sources: [], securities: [], access: [], parsers: [],
  };
  const calls = [];
  const user = { id: 1, email: "qa@example.test", full_name: "QA operator", is_admin: true, admin_role: role };
  const respond = (url, method = "GET", body = {}) => {
    const u = new URL(url, "http://localhost"), path = u.pathname;
    calls.push({ path, method, query: Object.fromEntries(u.searchParams), body });
    if (path === "/api/auth/me") return { user };
    if (path === "/api/companies") return { ok: true, companies: [] };
    if (path === "/api/securities") return { ok: true, securities: {} };
    if (path === "/api/notifications") return { ok: true, count: 0, notifications: [] };
    if (!path.startsWith("/api/admin/control")) return { ok: true, items: [] };
    const parts = path.replace("/api/admin/control", "").split("/").filter(Boolean);
    if (parts[0] === "session") return { actor: { ...user, role }, environment: "test", capabilities: role === "viewer" ? ["read", "export"] : ["read", "export", "retry", "comment", "draft", "test"], mfa_required_for_mutations: false };
    if (parts[0] === "overview") return { kpis: { auto_publication: 0.96, active_blockers: 2, coverage_complete: 64, coverage_total: 67, queued: rows.jobs.length }, attention: [incident], publications: [], jobs: rows.jobs, counts: { documents: { VALIDATED: 67 }, parsers: { VALIDATED: 64 }, facts: { verified: 1240 }, calculations: { verified: 342 }, analyses: { PUBLISHED: 64 }, publications: { PUBLISHED: 64 } } };
    if (parts[0] === "search") return { items: Object.entries(rows).flatMap(([collection, list]) => list.filter(r => JSON.stringify(r).toLowerCase().includes((u.searchParams.get("q") || "").toLowerCase())).map(r => ({ ...r, collection }))).slice(0, 15) };
    const collection = parts[0], id = decodeURIComponent(parts[1] || ""), action = parts[2];
    if (action === "preview") return { format: "XLSX", sheets: ["Balance", "Income"], sheet: u.searchParams.get("sheet") || "Balance", rows: [[{ address: "A1", value: "Net asset value" }, { address: "B1", value: "2026H1" }], [{ address: "A2", value: "Total NAV" }, { address: "B2", value: "123456" }]], next_row: null };
    if (action === "history") return { items: rows[collection].filter(r => r.id === id) };
    if (method === "POST") {
      if (action === "draft") { const item = { id: "rule-new", version: 1, title: body.title, config: body.config, category: body.category, status: "DRAFT", created_by: user.email }; rows.rules.push(item); return { ok: true, item }; }
      const job = { id: "job-new", version: 1, category: action, status: "QUEUED", entity_id: id, ticker: "UZNF", processed: 0, total: 1, checkpoint: 0, attempt: 1 };
      rows.jobs.push(job); return { ok: true, job_id: job.id, item: job };
    }
    if (id) return { item: rows[collection]?.find(r => r.id === id), related: {} };
    let items = [...(rows[collection] || [])];
    for (const key of ["ticker", "status", "standard", "period", "category"]) if (u.searchParams.get(key)) items = items.filter(r => u.searchParams.get(key).split(",").includes(r[key]));
    if (u.searchParams.get("q")) items = items.filter(r => JSON.stringify(r).toLowerCase().includes(u.searchParams.get("q").toLowerCase()));
    return { ok: true, items, total: items.length, next_cursor: null };
  };
  return { respond, calls, rows, user };
}
