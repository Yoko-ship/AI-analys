import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { parse } from "@babel/parser";

function walk(node, visit) {
  if (!node || typeof node !== "object") return;
  visit(node);
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(child => walk(child, visit));
    else if (value && typeof value === "object") walk(value, visit);
  }
}

for (const file of ["features/research/useResearchState.js", "features/news/useNewsFeed.js",
  "features/news/useNewsCalendar.js", "features/market/useMarketEnrichment.js", "admin/useAdminData.js"]) {
  test(`${file} owns state without rendering`, () => {
    const ast = parse(fs.readFileSync(path.join("frontend/src", file), "utf8"), { sourceType: "module", plugins: ["jsx"] });
    walk(ast, node => assert.ok(!["JSXElement", "JSXFragment"].includes(node.type), "State modules must not render UI"));
  });
}

for (const file of ["features/research/AnalysisWorkspace.jsx", "features/research/ComparisonWorkspace.jsx",
  "features/news/NewsCalendarView.jsx", "features/news/NewsView.jsx", "admin/CompanyImportsSection.jsx"]) {
  test(`${file} renders without requesting remote data`, () => {
    const ast = parse(fs.readFileSync(path.join("frontend/src", file), "utf8"), { sourceType: "module", plugins: ["jsx"] });
    walk(ast, node => {
      if (node.type === "CallExpression" && node.callee.type === "Identifier") {
        assert.ok(!["fetch", "apiFetch", "readJson"].includes(node.callee.name), "Requests belong in the state module");
      }
    });
  });
}
