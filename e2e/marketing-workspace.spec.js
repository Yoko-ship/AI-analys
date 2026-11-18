import { test, expect } from "@playwright/test";

// The acceptance server has its own catalogue, model and analytics database.
// Set MARKETING_ACCEPTANCE_URL to run against it with the built frontend.
test("editor decisions, campaign planning, measured journeys and experiments", async ({ page, context, browser }) => {
  test.skip(!process.env.MARKETING_ACCEPTANCE_URL, "Requires isolated acceptance data");
  test.setTimeout(240000);
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "qa");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  await page.route("**/api/auth/me", route => route.fulfill({json:{user:{id:1, is_admin:true, email:"editor@example.test"}}}));
  await page.goto(process.env.MARKETING_ACCEPTANCE_URL + "/admin/marketing");
  const post = page.getByLabel("Telegram post");
  await expect(post).toHaveValue(/NGQS \+20%/);
  await expect(post).toHaveValue(/39 680.*47 616/s);
  await page.getByRole("button",{name:"UZINP −17,24%"}).click();
  await expect(post).toHaveValue(/5 800.*4 800/s);
  await page.getByRole("button",{name:"NGQS +20%"}).click();
  await expect(page.getByText("Дивиденд", {exact:true})).toHaveCount(0);
  const weekly = page.getByRole("region",{name:"What to promote this week"});
  await expect(weekly).toContainText("3 of 21",{timeout:180000});
  await expect(weekly).toContainText("/heatmap");
  await post.fill("Отредактировано.\n" + await post.inputValue());
  await page.getByLabel("Editorial reason").fill("Readers want dividend amounts");
  await page.getByRole("button", {name:"Save edit", exact:true}).click();
  await expect(page.getByText("Edited", {exact:true}).first()).toBeVisible();
  await page.reload();
  await expect(post).toHaveValue(/Отредактировано/);
  await page.getByRole("button",{name:"Mark published"}).click();
  await expect(page.getByText("Published",{exact:true}).first()).toBeVisible();
  await page.getByRole("button",{name:"O‘zbekcha"}).click();
  await page.getByRole("button",{name:"Skip post"}).click();
  await expect(page.getByText("Skipped",{exact:true}).first()).toBeVisible();
  await page.getByLabel("Campaign goal").fill("Help first-time investors understand daily stock price changes on the market page.");
  await page.getByRole("button",{name:"Generate plan"}).click();
  await expect(page.getByLabel("Weekly actions")).toHaveValue(/.{25}/s, {timeout:190000});
  await expect(page.getByLabel("Audience")).toHaveValue(/.{4}/);
  await expect(page.getByLabel("Weekly actions")).toHaveValue(/market|stock|price/i);
  await page.getByLabel("Audience").fill("First-time investors in Uzbekistan");
  await page.getByRole("button",{name:"Approve plan"}).click();
  await expect(page.getByRole("link",{name:"Campaign link"})).toHaveAttribute("href", /utm_campaign=plan-/);
  await page.reload();
  await expect(page.getByLabel("Audience")).toHaveValue("First-time investors in Uzbekistan");
  await page.getByLabel("Experiment name").fill("Market or heatmap");
  await page.getByLabel("Destination A").selectOption("/market");
  await page.getByLabel("Destination B").selectOption("/heatmap");
  await page.getByRole("button",{name:"Start experiment"}).click();
  const completed = page.locator("article").filter({has:page.getByRole("heading",{name:"Completed landing test"})});
  await expect(completed).toContainText("A performed better");
  await expect(completed).toContainText("85 / 100");
  await expect(completed).toContainText("20 / 100");
  const link = await page.locator("article").filter({has:page.getByRole("heading",{name:"Market or heatmap"})})
    .getByRole("link",{name:"Experiment link"}).getAttribute("href");
  const localLink = process.env.MARKETING_ACCEPTANCE_URL + new URL(link).pathname;
  const first = await context.request.get(localLink,{maxRedirects:0});
  expect(first.headers().location).toMatch(/(market|heatmap).*utm_campaign=exp-/);
  expect((await context.request.get(localLink,{maxRedirects:0})).headers().location).toBe(first.headers().location);
  await expect(page.getByText(/Collecting evidence/)).toBeVisible();
  const row = page.getByRole("row").filter({hasText:"mover-1-ru"});
  await expect(row.getByRole("cell")).toHaveText(["mover-1-ru","4","4","6","2","1"]);
  await expect(page.getByText(/2 of 4 visits ended on the landing page/)).toBeVisible();
  const campaign = new URL(await page.getByRole("link",{name:"Campaign link"}).getAttribute("href"));
  const guest = await browser.newContext();
  try {
    const reader = await guest.newPage();
    const campaignRow = page.getByRole("row").filter({hasText:campaign.searchParams.get("utm_campaign")});
    await reader.goto(process.env.MARKETING_ACCEPTANCE_URL + campaign.pathname + campaign.search, {waitUntil:"domcontentloaded"});
    await expect(async()=>{
      await page.reload();
      await expect(campaignRow.getByRole("cell").nth(1)).toHaveText("1", {timeout:1500});
    }).toPass({timeout:15000});
    await reader.goto(process.env.MARKETING_ACCEPTANCE_URL + (campaign.pathname.endsWith("/news")?"/market":"/news"), {waitUntil:"domcontentloaded"});
    await expect(async()=>{
      await page.reload();
      await expect(campaignRow.getByRole("cell")).toHaveText([campaign.searchParams.get("utm_campaign"),"1","1","2","1","0"], {timeout:2000});
    }).toPass({timeout:15000});
  } finally { await guest.close(); }
  await weekly.getByRole("button",{name:"Approve suggestion"}).click();
  await page.reload();
  await expect(weekly).toContainText("Approved");
  const approved = page.locator(".marketing-record").filter({hasText:"Help readers of /market discover /heatmap"});
  await expect(approved.getByRole("link",{name:"Campaign link"})).toHaveAttribute("href", /heatmap.*utm_campaign=plan-weekly/);
});
