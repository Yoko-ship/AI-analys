export function mapAreaValue(row,mode){
 if(mode==='equal')return 1;
 const value=mode==='turnover'?row.stockVolume:mode==='capitalization'?row.marketCap:Math.abs(row.changePercent);
 return Number.isFinite(value)&&value>0?value:0;
}
