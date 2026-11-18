import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

for (const width of [390, 1440]) test(`create, share and measure a feature campaign at ${width}px`, async ({page, context}, info) => {
  const state = {items: []};
  await page.setViewportSize({width, height: 920});
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => {
    localStorage.setItem("uz_stock_analyzer_token", "admin");
    localStorage.setItem("uz_stock_analyzer_language", "en");
  });
  const base = "/api/admin/marketing";
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const send = (json, status=200) => route.fulfill({json, status});
    if (path === "/api/auth/me") return send({user:{id:1,is_admin:true,email:"editor@example.test"}});
    if (path === base + "/weekly-idea") return send({status:"empty"});
    if (path === base + "/workspace") {
      const weekly = Object.fromEntries(state.items.filter(i=>i.status==="published").map(i=>[i.tag,{visits:12,readers:10,pages:19,continued:6,returned:2}]));
      return send({plans:[],experiments:[],history:[],report:{available:true,weekly}});
    }
    if (path === base + "/campaign-posts" && route.request().method()==="GET") return send(state);
    if (path === base + "/campaign-posts") {
      const {request_id:id,edition,channel,destination} = route.request().postDataJSON();
      const tag = "feature-"+id;
      const item = {id,edition,channel,destination,tag,status:"draft",version:1,headline:"Explore the market map",
        body:"Open the map and compare companies by sector.", link:"https://uzstock.uz/heatmap?utm_source=telegram&utm_medium=social&utm_campaign="+tag+"&lang=en"};
      state.items=[item]; return send(item,201);
    }
    if (path.endsWith("/suggest")) return send({headline:"Which sector moved?",body:"Choose a sector on the heatmap to explore its companies."});
    if (path.startsWith(base+"/campaign-posts/")) {
      const {headline,body,publish}=route.request().postDataJSON();
      const item = {...state.items[0],headline,body,version:state.items[0].version+1,status:publish?"published":"draft"};
      state.items=[item]; return send(item);
    }
    return send({ok:true,items:[]});
  });
  await page.goto("/admin/marketing");
  const studio = page.getByRole("region", {name:"Feature campaigns"});
  await expect(studio).toBeVisible();
  await studio.getByLabel("Site feature").selectOption("/heatmap");
  await studio.getByLabel("Post language").selectOption("en");
  await studio.getByRole("button",{name:"Create post",exact:true}).click();
  await studio.getByLabel("Instructions for the AI").fill("Ask one short question.");
  await studio.getByRole("button",{name:"Suggest copy"}).click();
  await expect(studio.getByText("Which sector moved?",{exact:true})).toBeVisible();
  await studio.getByRole("button",{name:"Use suggestion"}).click();
  await studio.getByLabel("Headline").fill("Inside the market map");
  await studio.getByRole("button",{name:"Save draft"}).click();
  await page.reload();
  await expect(studio.getByLabel("Headline")).toHaveValue("Inside the market map");
  await studio.getByRole("button",{name:"Copy post",exact:true}).click();
  const copied = (await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,"\n");
  expect(copied).toContain("Inside the market map\n\nChoose a sector");
  expect(copied).toContain(state.items[0].link);
  const telegram = new URL(await studio.getByRole("link",{name:"Open in Telegram"}).getAttribute("href"));
  expect(telegram.searchParams.get("url")).toBe(state.items[0].link);
  const downloaded = page.waitForEvent("download");
  await studio.getByRole("button",{name:"Download image"}).click();
  const file = await downloaded;
  const bytes = await readFile(await file.path());
  expect([bytes.readUInt32BE(16),bytes.readUInt32BE(20)]).toEqual([1200,630]);
  await page.addScriptTag({path:createRequire(import.meta.url).resolve("jsqr")});
  const scanned = await page.evaluate(async encoded=>{
    const image = new Image();
    image.src = "data:image/png;base64,"+encoded;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width=600;canvas.height=315;
    const ctx=canvas.getContext("2d");
    ctx.drawImage(image,0,0,600,315);
    return window.jsQR(ctx.getImageData(0,0,600,315).data,600,315)?.data;
  },bytes.toString("base64"));
  expect(scanned).toBe(state.items[0].link);
  await studio.getByRole("button",{name:"Mark as published"}).click();
  await expect(studio.getByText("Published",{exact:true}).first()).toBeVisible();
  await expect(studio.getByText("12 visits")).toBeVisible();
  await expect(studio.getByText("2 returning readers")).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await studio.screenshot({path:info.outputPath("feature-campaign-"+width+".png")});
});
