export const SCREENERS_KEY = 'uzstock:screeners:v1';
function filters(value = {}) {
  return { sector: typeof value.sector === 'string' ? value.sector : '', query: typeof value.query === 'string' ? value.query.slice(0,100) : '',
    direction: ['gain','loss'].includes(value.direction) ? value.direction : 'all',
    period: ['1d','1w','1m','3m','6m','1y','ytd','3y','5y'].includes(value.period) ? value.period : '1d',
    type: ['stock','ordinary','preferred','bond'].includes(value.type) ? value.type : 'stock',
    favoriteOnly: value.favoriteOnly === true,
    sortKeys: Array.isArray(value.sortKeys) ? value.sortKeys.filter(s=>s&&typeof s.key==='string'&&['asc','desc'].includes(s.dir)).map(s=>({key:s.key,dir:s.dir})).slice(0,8) : [] };
}
export function readScreeners(storage) {
  try { const raw=JSON.parse(storage.getItem(SCREENERS_KEY)||'[]');
    return Array.isArray(raw)?raw.filter(s=>s&&typeof s.id==='string'&&typeof s.name==='string').slice(0,30).map(s=>({id:s.id,name:s.name.slice(0,70),filters:filters(s.filters)})):[];
  } catch { return []; }
}
export function saveScreener(storage, name, values) {
  const title=String(name||'').trim().slice(0,70); if(!title) throw new Error('Name required');
  const rows=readScreeners(storage); const existing=rows.find(s=>s.name===title);
  const item={id:existing?.id||crypto.randomUUID(),name:title,filters:filters(values)};
  const next=[item,...rows.filter(s=>s.id!==item.id)].slice(0,30);
  storage.setItem(SCREENERS_KEY,JSON.stringify(next)); return next;
}
export function removeScreener(storage,id) { const next=readScreeners(storage).filter(s=>s.id!==id); storage.setItem(SCREENERS_KEY,JSON.stringify(next)); return next; }
export function matchesDirection(change,direction) {
  return direction==='all'||(Number.isFinite(change)&&(direction==='gain'?change>0:change<0));
}
