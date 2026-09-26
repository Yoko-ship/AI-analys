import { test, expect } from "@playwright/test";

const flow = (date, ticker, coupon, principal = 0) => ({ date, ticker, coupon, principal, source: "reconstructed" });
const calendar = {
  ok: true, today: "2026-09-26",
  months: Array.from({ length: 60 }, (_, i) => {
    const date = new Date(Date.UTC(2026, 8 + i, 1));
    return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1 };
  }),
  flows: [flow("2026-09-27", "SEPT", 1e6), flow("2026-10-03", "EDGEA", 1e6),
    flow("2026-10-17", "MID", 2e6), flow("2026-10-19", "EDGEB", 3e6, 1e7),
    flow("2026-10-20", "OUTSIDE", 4e6), flow("2026-12-31", "YEAR", 5e6),
    flow("2027-01-01", "NEWYEAR", 6e6), flow("2028-02-29", "LEAP", 7e6),
    flow("2031-08-31", "LAST", 8e6)],
};

async function openCalendar(page, response = calendar) {
  const errors = [];
  // The sponsor has separate smoke coverage; keep it from covering date controls.
  await page.addInitScript(() => sessionStorage.setItem("uz_sponsor_seen", "1"));
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/bonds/calendar") {
      expect(url.searchParams.get("months")).toBe("60");
      return json(response);
    }
    if (url.pathname === "/api/bonds") return json({ ok: true, items: [], count: 0 });
    if (url.pathname === "/api/auth/me") return json({ user: null }, 401);
    return json({ ok: true });
  });
  await page.goto("/bonds");
  await page.getByRole("button", { name: "Календарь выплат", exact: true }).click();
  return errors;
}

async function choosePeriod(page, from, to) {
  await page.getByLabel("С", { exact: true }).fill(from);
  await page.getByLabel("По", { exact: true }).fill(to);
  await page.locator(".bondsec-period").evaluate((form) => form.scrollIntoView({ block: "center" }));
  await page.getByRole("button", { name: "Показать", exact: true }).click();
}

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`bond payment period updates totals, feed and calendar at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const errors = await openCalendar(page);
    await expect(page.getByRole("button", { name: "30 дней", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".bondsec-pay")).toHaveCount(5);
    await choosePeriod(page, "2026-10-03", "2026-10-19");
    await expect(page.locator(".bondsec-pay-tk")).toHaveText(["EDGEA", "MID", "EDGEB"]);
    await expect(page.locator(".bondsec-tile-v")).toHaveText(["03.10.2026", "3", "10,00 млн", "6,00 млн"]);
    await expect(page.getByRole("img", { name: "Выплаты по месяцам" }).locator("title")).toContainText("Купоны: 6,00 млн");
    await expect(page.getByLabel("Месяц календаря")).toHaveValue("2026-10");
    await expect(page.locator('.bondsec-cell[data-date="2026-10-19"]')).toContainText("EDGEB");
    await expect(page.locator('.bondsec-cell[data-date="2026-10-20"]')).not.toContainText("OUTSIDE");
    await expect(page.locator('.bondsec-cell[data-date="2026-10-20"]')).toHaveClass(/outside-period/);
    await expect(page.getByRole("button", { name: "Предыдущий месяц" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Следующий месяц" })).toBeDisabled();
    if (viewport.width === 1280) await page.locator(".theme-toggle").click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("custom-period.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

    await page.getByRole("button", { name: "1 год", exact: true }).click();
    await expect(page.locator(".bondsec-pay")).toHaveCount(7);
    await page.getByLabel("Месяц календаря").selectOption("2026-12");
    await expect(page.locator('.bondsec-cell[data-date="2026-12-31"]')).toContainText("YEAR");
    await page.getByRole("button", { name: "Следующий месяц" }).click();
    await expect(page.getByLabel("Месяц календаря")).toHaveValue("2027-01");
    await expect(page.locator('.bondsec-cell[data-date="2027-01-01"]')).toContainText("NEWYEAR");
    await page.getByRole("button", { name: "Предыдущий месяц" }).click();
    await expect(page.getByLabel("Месяц календаря")).toHaveValue("2026-12");

    await page.getByRole("button", { name: "90 дней", exact: true }).click();
    await expect(page.getByLabel("По", { exact: true })).toHaveValue("2026-12-25");
    await expect(page.locator(".bondsec-pay")).toHaveCount(5);
    await page.getByRole("button", { name: "30 дней", exact: true }).click();
    await expect(page.getByLabel("По", { exact: true })).toHaveValue("2026-10-26");
    await page.locator(".bondsec-pay").filter({ hasText: "EDGEA" }).click();
    await expect(page).toHaveURL(/\/bond\/EDGEA/);
    expect(errors).toEqual([]);
  });
}

test("empty and invalid periods preserve an honest, usable calendar", async ({ page }) => {
  const errors = await openCalendar(page);
  await choosePeriod(page, "2026-11-01", "2026-11-30");
  await expect(page.locator(".bondsec-days")).toContainText("В выбранном периоде выплат нет.");
  await expect(page.locator(".bondsec-tile-v")).toHaveText(["—", "0", "0", "0"]);
  await expect(page.getByLabel("Месяц календаря")).toHaveValue("2026-11");
  await choosePeriod(page, "2026-12-01", "2026-11-30");
  await expect(page.getByRole("alert")).toContainText("Дата окончания");
  await expect(page.getByLabel("Месяц календаря")).toHaveValue("2026-11");
  await choosePeriod(page, "2026-09-25", "2026-10-01");
  await expect(page.getByRole("alert")).toContainText("доступном периоде");
  await choosePeriod(page, "", "2026-10-01");
  await expect(page.getByRole("alert")).toContainText("Укажите обе даты");
  await choosePeriod(page, "2028-02-29", "2028-02-29");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".bondsec-pay-tk")).toHaveText(["LEAP"]);
  await expect(page.locator(".bondsec-cell")).toHaveCount(29);
  await choosePeriod(page, "2031-08-31", "2031-08-31");
  await expect(page.locator(".bondsec-pay-tk")).toHaveText(["LAST"]);
  await choosePeriod(page, "2026-09-26", "2031-08-31");
  await expect(page.getByLabel("Месяц календаря").locator("option")).toHaveCount(60);
  await expect(page.locator(".bondsec-pay")).toHaveCount(9);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("Uzbek and English controls keep the selected dates and support keyboard submit", async ({ page }, testInfo) => {
  const errors = await openCalendar(page);
  await page.locator("#languageSelect").selectOption("uz");
  await expect(page.locator(".bondsec-period")).toContainText("To'lovlar davri");
  await page.getByLabel("Boshlanish", { exact: true }).fill("2026-12-31");
  await page.getByLabel("Tugash", { exact: true }).fill("2027-01-01");
  await page.getByLabel("Tugash", { exact: true }).press("Enter");
  await expect(page.locator(".bondsec-pay-tk")).toHaveText(["YEAR", "NEWYEAR"]);
  await expect(page.locator(".bondsec-dow")).toHaveText("DuSeChPaJuShYa");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("uzbek-period.png"), fullPage: true });
  await page.locator("#languageSelect").selectOption("en");
  await expect(page.getByLabel("From", { exact: true })).toHaveValue("2026-12-31");
  await expect(page.getByLabel("To", { exact: true })).toHaveValue("2027-01-01");
  await expect(page.getByLabel("Calendar month")).toHaveValue("2026-12");
  expect(errors).toEqual([]);
});

for (const [name, response, message] of [
  ["no schedules", { ...calendar, flows: [] }, "Будущих выплат не видно"],
  ["failed request", { ok: false }, "Календарь недоступен"],
]) {
  test(`calendar handles ${name}`, async ({ page }) => {
    const errors = await openCalendar(page, response);
    await expect(page.getByText(message, { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });
}
