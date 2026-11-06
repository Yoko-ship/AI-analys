const pick=(lang,ru,uz,en)=>({ru,uz,en}[lang]||ru);

export function reportRatioUnit(unit,lang){
  if(['percent','%'].includes(unit))return '%';
  if(unit==='UZS_thousand')return pick(lang,' тыс. UZS',' ming UZS',' thousand UZS');
  if(unit==='UZS_per_share')return pick(lang,' UZS/акция',' UZS/aksiya',' UZS/share');
  return unit==='ratio'?' ×':'';
}

export function reportRatioReason(item,lang){
  const reasons={
    EPS_INPUTS_MISSING:['Нет подтверждённой EPS или данных для её расчёта','Tasdiqlangan EPS yoki hisoblash ma’lumotlari yo‘q','Verified EPS or the inputs needed to calculate it are unavailable'],
    DEBT_INPUTS_MISSING:['Не подтверждён полный состав долга или положительный капитал','Qarz tarkibi yoki musbat kapital tasdiqlanmagan','Complete debt components or positive equity are unverified'],
    BOOK_OR_QUOTE_INPUTS_MISSING:['Нет подтверждённой базы обычных акций или актуальной котировки','Oddiy aksiyalar bazasi yoki dolzarb kotirovka tasdiqlanmagan','Verified ordinary-share inputs or a current quote are unavailable'],
    INPUTS_MISSING:['Компоненты отсутствуют или недопустимы','Tarkibiy qismlar yetishmaydi yoki yaroqsiz','Components are incomplete or invalid'],
  };
  const texts=reasons[item.reason_code];
  return texts?pick(lang,...texts):item.reason_code||pick(lang,...reasons.INPUTS_MISSING);
}
