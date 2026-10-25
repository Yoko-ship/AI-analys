// Presentation only: financial values and period calculations come from the
// approved source matrix. Never substitute the HTML reference's demo values.
export function amount(cell,unit='UZS_thousand') {
  if(cell?.value==null||!['valid','warn'].includes(cell.quality))return null;
  const value=Number(cell.value);
  return Number.isFinite(value)?value/(unit==='UZS_thousand'?1e6:1):null;
}
export function columnsFor(data,statement) {
  return (data?.columns||[]).filter(c=>statement==='bs'?c.basis!=='ttm':c.basis!=='as_of');
}
export function selectedColumn(data,kind='flow') {
  return columnsFor(data,kind==='stock'?'bs':'pl').at(-1);
}
export function ratioColumn(data,row) {
  const flow=selectedColumn(data);
  if(flow?.basis==='ttm'&&row.cells?.[flow.key]?.quality==='not_applicable') {
    return columnsFor(data,'bs').findLast(c=>c.end===flow.end)||flow;
  }
  return flow;
}
export function fundingShare(assets,equity,liabilities) {
  return [assets,equity,liabilities].every(v=>v!=null)&&assets>0&&equity>=0&&liabilities>=0&&Math.abs(assets-equity-liabilities)<.000001?equity/assets:null;
}
export function metricRow(data,field,statement) {
  const sections=statement?[data?.statements?.[statement]]:Object.values(data?.statements||{});
  return sections.flatMap(groups=>(groups||[]).flatMap(g=>g.rows)).find(r=>r.field===field);
}
export function fieldValue(data,field,column,statement) {
  const row=metricRow(data,field,statement);
  return amount(row?.cells?.[column?.key],row?.unit);
}
export function primaryField(data) {
  return ({bank:'netInterest',insurance:'insRevenue',fund:'nav',leasing:'revenue'})[data?.display_template]||'revenue';
}
export function growth(data,field) {
  const row=metricRow(data,field),cols=columnsFor(data,row?.kind==='stock'?'bs':'pl');
  const last=cols.at(-1);
  if(!last)return null;
  const previous=cols.slice(0,-1).reverse().find(c=>c.basis===last.basis&&c.end.slice(4)===last.end.slice(4)&&Number(c.end.slice(0,4))===Number(last.end.slice(0,4))-1);
  const a=amount(row?.cells[last.key],row?.unit),b=amount(row?.cells[previous?.key],row?.unit);
  return a!=null&&b>0?(a/b-1)*100:null;
}
function literal(value) {
  const text=String(value??'');
  return '"'+(/^[=+@\t\r\n]/.test(text)?"'"+text:text).replaceAll('"','""')+'"';
}
export function statementCsv(data,statement,detail=true) {
  const columns=columnsFor(data,statement);
  const lines=[['Показатель','Единицы',...columns.map(c=>c.label)]];
  for(const group of data.statements[statement]||[]) {
    lines.push([group.label]);
    for(const row of group.rows.filter(r=>detail||!r.detail))lines.push([row.label,'млрд UZS',...columns.map(c=>amount(row.cells[c.key],row.unit)??'')]);
  }
  return '\ufeff'+lines.map(line=>line.map(literal).join(';')).join('\r\n');
}
export function downloadStatement(data,statement,detail) {
  const url=URL.createObjectURL(new Blob([statementCsv(data,statement,detail)],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`${data.ticker}_IFRS_${data.scope}_${statement}.csv`;
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function notesPages(data) {
  const forms=data?.source_forms||[],end=selectedColumn(data,'stock')?.end;
  return forms.filter(f=>f.period_end===end).flatMap(f=>(f.documents||[]).filter(d=>d.form==='Notes').map(d=>({...d,url:d.source_url||f.source_url,period:f.period_end})));
}
