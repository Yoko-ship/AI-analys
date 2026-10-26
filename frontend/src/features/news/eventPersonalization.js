const topicPatterns={banks:/bank|банк|банки/i,telecom:/telecom|телеком|aloqa/i,insurance:/insuran|страх|sug.?urta/i,energy:/energy|energi|энерг|нефт|gas|газ/i,industry:/industr|промышлен|sanoat|cement|цемент/i,low_volatility:/volatility|волатиль|o.zgaruvchan/i,growth:/growth|рост|o.sish/i,fundamentals:/profit|earnings|revenue|прибыл|выручк|отч[её]т|hisobot|foyda/i};
export function matchesInterests(story,interests=[],securities={}){
 const text=[story.organization,...Object.values(story.title||{}),...Object.values(story.summary||{}),...(story.tickers||[]).map(t=>securities[t]?.sector||'')].join(' ');
 return interests.some(topic=>topic==='dividends'?story.category==='dividends':topic==='corporate'?Boolean(story.category):topic==='bonds'?(story.security_types||[]).includes('bond'):Boolean(topicPatterns[topic]?.test(text)));
}
export function rankEvent(story,mine,today){
 const days=(Date.parse(story.event_date||story.payment_start)-Date.parse(today))/86400000;
 return (3-story.priority)*10+((story.tickers||[]).some(t=>mine.has(t))?40:0)+(days>=0&&days<=7?8:0);
}
