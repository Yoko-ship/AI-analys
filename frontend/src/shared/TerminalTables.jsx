import React from "react";
import { tableCsv } from "../lib/terminalWorkspace.js";
import { logTerminalEvent } from "../lib/terminalJournal.js";
export const words = (lang, ru, uz, en) => ({ru,uz,en}[lang] || ru);
export function downloadCsv(rows, name, context={}) {
  const blob = new Blob([tableCsv(rows)],{type:"text/csv;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href=url;a.download=`${name}.csv`;a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  logTerminalEvent("export",context);
}

// Give every terminal table an export, including shared financial components.
// Buttons are siblings of tables, never part of the exported cells.
export function useTableExports(root, context) {
  const current=React.useRef(context);current.current=context;
  React.useEffect(()=>{
    const node=root.current;if(!node)return undefined;
    const attached=new Map();
    const scan=()=>{
      for(const [table,button] of attached) if(!node.contains(table)){button.remove();attached.delete(table);}
      node.querySelectorAll("table:not([data-own-export])").forEach((table)=>{
        if(attached.has(table))return;
        const button=document.createElement("button");button.type="button";button.className="ghost-btn terminal-csv";button.textContent="CSV";
        button.setAttribute("aria-label","CSV");
        button.onclick=()=>{
          const owner=table.closest("[data-terminal-ticker]"), currency=table.closest("[data-currency]");
          const ctx={...current.current,...(owner?{ticker:owner.dataset.terminalTicker,function:owner.dataset.terminalFunction,standard:owner.dataset.terminalStandard,scope:owner.dataset.terminalScope}:{})};
          const metadata=[["Ticker",ctx.ticker||"market"],["Function",ctx.function||""],["Standard",ctx.standard||""],["Scope",ctx.scope||""]];
          if(currency){metadata.push(["Currency",currency.dataset.currency]);currency.querySelectorAll(".terminal-fx-rates li").forEach(li=>metadata.push(["CBU FX",li.innerText.trim()]));}
          downloadCsv([...metadata,[],...Array.from(table.rows,row=>Array.from(row.cells,c=>c.innerText.trim()))],
            `UZStock-${ctx.function || "table"}-${ctx.ticker || "market"}`,ctx);
        };
        table.before(button);attached.set(table,button);
      });
    };
    scan();const observer=new MutationObserver(scan);observer.observe(node,{childList:true,subtree:true});
    return()=>{observer.disconnect();for(const button of attached.values())button.remove();};
  },[root]);
}
