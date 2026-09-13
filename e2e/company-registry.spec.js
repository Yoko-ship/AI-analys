import { test, expect } from "@playwright/test";


const TICKER = "UPOS";
const SECURITY = {
  ticker: TICKER,
  name: "O'zbekiston pochtasi",
  company_name: "O'zbekiston pochtasi",
  security_type: "stock",
  last_price: 1_250,
  close_price: 1_240,
  industry: "Transport",
};

const REGISTRY = {
  company: {
    tin: "200833833",
    name: '"O`ZBEKISTON POCHTASI" AKSIYADORLIK JAMIYATI',
    shortName: '"O`ZBEKISTON POCHTASI" AJ',
    status: 0,
    statusUpdated: null,
    opf: 153,
    kfs: 100,
    oked: "53100",
    soato: 1726266,
    soogu: "03593",
    sooguRegistrator: "07294",
    taxpayerType: 3,
    registrationDate: "25.08.2003",
    registrationNumber: "10-001310",
    reregistrationDate: "16.07.2026",
    liquidationDate: null,
    taxMode: 1,
    vatNumber: 326030013813,
    businessFund: 52563506760,
    opfDetail: { code: "153", name_ru: "АКЦИОНЕРНОЕ ОБЩЕСТВО", name_uz_latn: "AKSIYADORLIK JAMIYATI" },
    sooguDetail: { code: "03593", name: "Ministry of Digital Technologies", name_ru: "Министерство цифровых технологий", name_uz_latn: "Raqamli texnologiyalar vazirligi" },
    statusDetail: { code: "0", name: "Active with Tax Liabilities", name_ru: "Действующее и имеющее налоговые обязательства", name_uz_latn: "Faoliyat ko'rsatayotgan", group: "ACTIVE" },
    okedDetail: { code: "53100", name: "Postal services", name_ru: "ПОЧТОВЫЕ УСЛУГИ", name_uz_latn: "POCHTA XIZMATI" },
    streetName: "Oloy ko'chasi",
  },
  companyBillingAddress: {
    postcode: "100000",
    region: { name: "Tashkent city", name_ru: "город Ташкент", name_uz_latn: "Toshkent shahri" },
    district: { name: "Yunusabad district", name_ru: "Юнусабадский район", name_uz_latn: "Yunusobod tumani" },
    streetName: "Oloy ko'chasi",
  },
  director: { lastName: "FAYZULLAYEV", firstName: "ALISHER", middleName: "NASIBULLAYEVICH" },
  accountant: { lastName: "YUSUPOV", firstName: "YUSUPBOY", middleName: "ERGASHEVICH" },
};


test("Soliq registry is loaded only for the opened company and renders the full record", async ({ page }, testInfo) => {
  let registryRequests = 0;
  let verifiedLocation = null;
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") runtimeErrors.push(message.text()); });

  await page.route("https://www.google.com/maps?**", (route) => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: "<!doctype html><title>Map fixture</title>",
  }));
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/securities") return json({ ok: true, securities: { [TICKER]: SECURITY } });
    if (path === "/api/market/stocks") return json({ stocks: [SECURITY] });
    if (path === `/api/company/${TICKER}/registry`) {
      registryRequests += 1;
      return json({ ok: true, ticker: TICKER, tin: "200833833", org_id: "667", type: "full", registry: REGISTRY, location: verifiedLocation });
    }
    if (path === `/api/securities/${TICKER}/info`) return json({ ok: true, security: SECURITY, wiki: {} });
    if (path === `/api/price-history/${TICKER}`) return json({ ok: true, points: [], adjustments: [] });
    if (path === `/api/company/${TICKER}/metrics`) return json({ ok: true, quality: {} });
    if (path === `/api/catalog/company/${TICKER}/reports`) return json({ ok: true, reports: [], ratios: {} });
    if (path === `/api/dividends/${TICKER}`) return json({ ok: true, items: [] });
    if (path === "/api/auth/me") return json({ user: null }, 401);
    return json({ ok: true, items: [], series: {} });
  });

  await page.goto("/market");
  await expect.poll(() => registryRequests).toBe(0);

  await page.goto(`/company/${TICKER}`);
  const card = page.getByTestId("company-registry");
  await expect(card).toBeVisible();
  await expect.poll(() => registryRequests).toBe(1);
  await expect(card).toContainText("Регистрационные данные");
  await expect(card).toContainText("200833833");
  await expect(card).toContainText("АКЦИОНЕРНОЕ ОБЩЕСТВО");
  await expect(card).toContainText("ПОЧТОВЫЕ УСЛУГИ");
  await expect(card).toContainText("Юнусабадский район");
  await expect(card).toContainText("FAYZULLAYEV ALISHER NASIBULLAYEVICH");
  await expect(card).toContainText(/52.563.506.760 UZS/);
  await expect(card).not.toContainText("Дата изменения статуса");
  await expect(card).not.toContainText("Дата прекращения деятельности");
  await expect(card).not.toContainText("—");
  const map = card.locator('iframe[title="Расположение компании"]');
  await expect(map).toHaveCount(0);

  verifiedLocation = { latitude: 41.311081, longitude: 69.240562 };
  await page.reload();
  await expect.poll(() => registryRequests).toBe(2);
  await expect(map).toBeVisible();
  await expect(map).toHaveAttribute("src", "https://www.google.com/maps?q=41.311081,69.240562&z=17&output=embed");
  await expect(map).not.toHaveAttribute("src", /Yunusabad|Oloy|Uzbekistan/);

  const desktopShot = testInfo.outputPath("company-registry-desktop.png");
  await card.screenshot({ path: desktopShot });
  await testInfo.attach("company-registry-desktop", { path: desktopShot, contentType: "image/png" });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const mobileShot = testInfo.outputPath("company-registry-mobile.png");
  await card.screenshot({ path: mobileShot });
  await testInfo.attach("company-registry-mobile", { path: mobileShot, contentType: "image/png" });

  expect(runtimeErrors).toEqual([]);
});
