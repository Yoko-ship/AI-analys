import { ISSUER_FUNCTIONS, MARKET_FUNCTIONS } from "./terminalCommands.js";

export function tableCsv(rows) {
  const cell = value => {
    let text = value == null ? "" : String(value);
    if (typeof value === "string" && /^[\s]*[=+@-]/.test(text)) text = `'${text}`;
    return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  return "\uFEFF" + rows.map(row => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

export function filterRows(rows, filters, depositRate = null) {
  return rows.filter(row => {
    if (filters.query && !`${row.ticker} ${row.name}`.toLowerCase().includes(filters.query.toLowerCase())) return false;
    if (filters.kind && row.kind !== filters.kind) return false;
    if (filters.sector && row.sector !== filters.sector) return false;
    if (filters.above_deposit && !(depositRate != null && row.dy != null && row.dy > depositRate)) return false;
    for (const [key, bound] of Object.entries(filters)) {
      const match = /^(.*)_(min|max)$/.exec(key);
      if (!match || bound === "" || bound == null) continue;
      const value = row[match[1]];
      if (value == null || !Number.isFinite(Number(value)) || !Number.isFinite(Number(bound))) return false;
      if (match[2] === "min" ? value < Number(bound) : value > Number(bound)) return false;
    }
    return true;
  });
}

export function normalizeLayout(layout) {
  if (!Array.isArray(layout)) return [];
  return layout.filter(p => p && /^[A-Z0-9]{2,16}$/.test(p.ticker) && ISSUER_FUNCTIONS.some(f => f.code === p.func))
    .slice(0,4).map(p => ({ticker:p.ticker,func:p.func,form:p.form === "MSFO" ? "MSFO" : "NSBU",
      scope:p.form === "MSFO" && p.scope === "consolidated" ? "consolidated" : "separate"}));
}

export function screenFromUrl(url) {
  const q = new URL(url, "http://localhost").searchParams;
  const form = q.get("std") === "MSFO" ? "MSFO" : "NSBU";
  return {ticker:q.get("t")?.toUpperCase() || null,
    func:ISSUER_FUNCTIONS.some(f=>f.code===q.get("f")) ? q.get("f") : "SUM", form,
    scope:form === "MSFO" && q.get("scope") === "consolidated" ? "consolidated" : "separate",
    market:MARKET_FUNCTIONS.some(f=>f.code===q.get("view")) ? q.get("view") : null,fullHistory:q.get("h")==="all"};
}

export function screenUrl(screen, current = "/catalog") {
  const url = new URL(current, "http://localhost");
  for (const key of ["t","f","std","scope","view","h"]) url.searchParams.delete(key);
  for (const [key, value] of Object.entries({t:screen.ticker,f:screen.func !== "SUM" ? screen.func : null,
    std:screen.form === "MSFO" ? "MSFO" : null,scope:screen.form === "MSFO" ? screen.scope : null,
    view:screen.market,h:screen.fullHistory ? "all" : null})) if(value) url.searchParams.set(key,value);
  return url.pathname + url.search + url.hash;
}

export function profitSparkline(values = {}) {
  const rows=Object.entries(values).filter(([year,value])=>/^\d{4}$/.test(year)&&value!=null&&Number.isFinite(value)).map(([year,value])=>({year:Number(year),value})).sort((a,b)=>a.year-b.year);
  if(!rows.length)return {segments:[],first:null,last:null};
  const min=Math.min(...rows.map(r=>r.value)),max=Math.max(...rows.map(r=>r.value)),first=rows[0].year,last=rows.at(-1).year;
  const segments=[];
  rows.forEach((r,i)=>{
    if(i===0||r.year!==rows[i-1].year+1)segments.push([]);
    segments.at(-1).push({x:2+(r.year-first)/(last-first||1)*96,y:max===min?18:32-(r.value-min)/(max-min)*28});
  });
  return {segments,first,last};
}
