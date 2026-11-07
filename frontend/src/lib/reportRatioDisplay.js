const pick=(lang,ru,uz,en)=>({ru,uz,en}[lang]||ru);

export function reportRatioUnit(unit,lang){
  if(['percent','%'].includes(unit))return '%';
  if(unit==='UZS_thousand')return pick(lang,' тыс. UZS',' ming UZS',' thousand UZS');
  if(unit==='UZS_per_share')return pick(lang,' UZS/акция',' UZS/aksiya',' UZS/share');
  return unit==='ratio'?' ×':'';
}

export function reportRatioReason(item,lang){
  const inputs={
    common_equity:['капитал обычных акционеров','oddiy aksiyadorlar kapitali','ordinary shareholders’ equity'],
    ordinary_shares:['число обычных акций на отчётную дату','hisobot sanasidagi oddiy aksiyalar soni','ordinary shares at the reporting date'],
    usable_quote:['подходящая котировка обычной акции','oddiy aksiyaning mos kotirovkasi','a usable ordinary-share quote'],
    profit_ordinary:['прибыль обычных акционеров','oddiy aksiyadorlarga tegishli foyda','profit attributable to ordinary shareholders'],
    weighted_average_shares:['средневзвешенное число обычных акций за этот период','shu davrdagi oddiy aksiyalarning o‘rtacha tortilgan soni','weighted-average ordinary shares for this period'],
    reported_eps_conflict:['согласованная опубликованная EPS','bir-biriga mos e’lon qilingan EPS','consistent reported EPS'],
  };
  const missing=Array.isArray(item.missing_inputs)?[...new Set(item.missing_inputs)].filter(key=>inputs[key]):[];
  if(missing.length)return pick(lang,'Отсутствуют или не подтверждены: ','Yetishmaydi yoki tasdiqlanmagan: ','Missing or unverified: ')+missing.map(key=>pick(lang,...inputs[key])).join('; ');
  const reasons={
    EPS_INPUTS_MISSING:['Нет подтверждённой EPS или данных для её расчёта','Tasdiqlangan EPS yoki hisoblash ma’lumotlari yo‘q','Verified EPS or the inputs needed to calculate it are unavailable'],
    DEBT_INPUTS_MISSING:['Не подтверждён полный состав долга или положительный капитал','Qarz tarkibi yoki musbat kapital tasdiqlanmagan','Complete debt components or positive equity are unverified'],
    BOOK_OR_QUOTE_INPUTS_MISSING:['Нет подтверждённой базы обычных акций или актуальной котировки','Oddiy aksiyalar bazasi yoki dolzarb kotirovka tasdiqlanmagan','Verified ordinary-share inputs or a current quote are unavailable'],
    INPUTS_MISSING:['Компоненты отсутствуют или недопустимы','Tarkibiy qismlar yetishmaydi yoki yaroqsiz','Components are incomplete or invalid'],
  };
  const texts=reasons[item.reason_code];
  return texts?pick(lang,...texts):item.reason_code||pick(lang,...reasons.INPUTS_MISSING);
}
