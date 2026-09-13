import test from "node:test";
import assert from "node:assert/strict";

import {
  companyReportPresentation,
  reportFormLabel,
} from "../frontend/src/lib/reportPresentation.js";

test("IFRS packages stay financial statements even when their PDF begins with an audit opinion", () => {
  const item = companyReportPresentation({
    report_form: "MSFO",
    period_type: "annual",
    year: 2025,
    title: "Годовой отчет",
  }, "ru");
  assert.equal(item.title, "Финансовая отчётность по МСФО · 2025");
  assert.equal(item.formLabel, "МСФО");
  assert.match(item.description, /аудитор/i);
});

test("standalone audit opinions are never labeled IFRS", () => {
  const item = companyReportPresentation({
    report_form: "Audition",
    period_type: "annual",
    year: 2024,
  }, "ru");
  assert.equal(item.title, "Аудиторское заключение · 2024");
  assert.equal(item.formLabel, "Аудиторское заключение");
  assert.doesNotMatch(item.formLabel, /МСФО/);
  assert.equal(reportFormLabel("Audition", "uz"), "Auditor xulosasi");
});
