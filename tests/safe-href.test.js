// Links built from scraped, filed or model-written URLs (frontend/src/lib/safeHref.js).
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";
import { safeHref } from "../frontend/src/lib/safeHref.js";

describe("safeHref", () => {
  it("keeps web links and same-site paths", () => {
    assert.equal(safeHref("https://openinfo.uz/ru/facts/1"), "https://openinfo.uz/ru/facts/1");
    assert.equal(safeHref("http://example.test/a.pdf"), "http://example.test/a.pdf");
    assert.equal(safeHref("  HTTPS://Example.test/x  "), "HTTPS://Example.test/x");
    assert.equal(safeHref("/api/reports/42/pdf"), "/api/reports/42/pdf");
    assert.equal(safeHref("reports/42.xlsx"), "reports/42.xlsx");
  });

  it("drops script and data schemes, however they are disguised", () => {
    for (const value of [
      "javascript:alert(1)",
      "JavaScript:alert(1)",
      "  javascript:alert(1)",
      "java\tscript:alert(1)",
      "java\nscript:alert(1)",
      "\u0001javascript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "vbscript:msgbox(1)",
      "file:///etc/passwd",
    ]) {
      assert.equal(safeHref(value), undefined, JSON.stringify(value));
    }
  });

  it("gives no href for absent or non-string values", () => {
    for (const value of [undefined, null, "", "   ", 42, {}]) {
      assert.equal(safeHref(value), undefined);
    }
  });
});
