import { test, expect } from "@playwright/test";

test("a feature post takes a real reader from a tracked link to a second page", async ({page, browser}) => {
  const origin = process.env.MARKETING_ACCEPTANCE_URL;
  test.skip(!origin, "Requires isolated acceptance data");
  test.setTimeout(240000);
  await page.addInitScript(()=>{
    localStorage.setItem("uz_stock_analyzer_token","qa");
    localStorage.setItem("uz_stock_analyzer_language","en");
  });
  await page.route("**/api/auth/me", route=>route.fulfill({json:{user:{id:1,is_admin:true,email:"editor@example.test"}}}));
  await page.goto(origin+"/admin/marketing");
  const studio = page.getByRole("region",{name:"Feature campaigns"});
  await studio.getByLabel("Site feature").selectOption("/issuers");
  await studio.getByLabel("Post language").selectOption("uz");
  await studio.getByLabel("Publishing channel").selectOption("linkedin");
  await studio.getByRole("button",{name:"Create post",exact:true}).click();
  await expect(studio.getByRole("textbox",{name:"Post text",exact:true})).toHaveValue(/emitentlar katalogi/i);
  const landing = new URL(await studio.getByRole("link",{name:"View landing page"}).getAttribute("href"));
  expect(landing.pathname).toBe("/uz/issuers");
  expect(landing.searchParams.get("utm_source")).toBe("linkedin");
  const offline = route=>route.fulfill({status:503,json:{detail:"AI unavailable"}});
  await page.route("**/campaign-posts/*/suggest",offline);
  await studio.getByRole("button",{name:"Suggest copy"}).click();
  await expect(studio.getByRole("alert")).toContainText("AI is unavailable");
  await expect(studio.getByRole("button",{name:"Copy post"})).toBeEnabled();
  await page.unroute("**/campaign-posts/*/suggest",offline);
  await studio.getByLabel("Instructions for the AI").fill("Write in Uzbek Latin for a reader who knows a company name but not its ticker.");
  await studio.getByRole("button",{name:"Suggest copy"}).click();
  await studio.getByRole("button",{name:"Use suggestion"}).click({timeout:185000});
  const finalText = await studio.getByRole("textbox",{name:"Post text",exact:true}).inputValue();
  expect(finalText).toMatch(/kompaniya|korxona|emitent|tiker/i);
  await studio.getByRole("button",{name:"Save draft"}).click();
  await expect(studio.getByText("Draft saved")).toBeVisible();
  await page.reload();
  await expect(studio.getByRole("textbox",{name:"Post text",exact:true})).toHaveValue(finalText);
  const selectedId = await studio.getByLabel("Saved posts").inputValue();
  const posts = (await (await page.request.get(origin+"/api/admin/marketing/campaign-posts")).json()).items;
  const saved = posts.find(post=>post.id===selectedId);
  const revised = saved.headline.slice(0, 88) + " · UZStock";
  const elsewhere = await page.request.put(origin+"/api/admin/marketing/campaign-posts/"+selectedId,
    {data:{version:saved.version,body:saved.body,headline:revised,publish:false}});
  expect(elsewhere.ok()).toBe(true);
  await studio.getByRole("textbox",{name:"Post text",exact:true}).fill(finalText+" UZStock.");
  await studio.getByRole("button",{name:"Save draft"}).click();
  await expect(studio.getByRole("alert")).toContainText("changed in another tab");
  await studio.getByRole("button",{name:"Load saved version"}).click();
  await expect(studio.getByLabel("Headline")).toHaveValue(revised);
  await studio.getByRole("button",{name:"Mark as published"}).click();
  await expect(studio.getByText("Published",{exact:true}).first()).toBeVisible();
  const guest = await browser.newContext();
  try {
    const reader = await guest.newPage();
    await reader.goto(origin+landing.pathname+landing.search,{waitUntil:"domcontentloaded"});
    const headline = await studio.getByLabel("Headline").inputValue();
    const row = page.getByRole("row").filter({has:page.getByRole("cell",{name:headline,exact:true})});
    await expect(async()=>{
      await page.reload();
      await expect(row.getByRole("cell").nth(1)).toHaveText("1",{timeout:1500});
    }).toPass({timeout:20000});
    await reader.goto(origin+"/uz/market",{waitUntil:"domcontentloaded"});
    await expect(async()=>{
      await page.reload();
      await expect(row.getByRole("cell")).toHaveText([headline,"1","1","2","1","0"],{timeout:2000});
    }).toPass({timeout:20000});
  } finally { await guest.close(); }
});

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
