import React from 'react';
import {TermInfo} from '../../../shared/TermInfo.jsx';
import {words} from '../../../shared/TerminalTables.jsx';
import {metricApplies} from '../../../lib/terminalWorkspace.js';

const reasons={
  NOT_APPLICABLE:['Показатель не применяется к этому типу компании.','Bu ko‘rsatkich ushbu turdagi kompaniyaga qo‘llanmaydi.','This metric does not apply to this type of company.'],
  MARKET_CAP_UNAVAILABLE:['Нет подтверждённой рыночной капитализации для расчёта.','Hisoblash uchun tasdiqlangan bozor kapitallashuvi yo‘q.','Verified market capitalisation is unavailable.'],
  INCOMPLETE_MARKET_CAP:['Не хватает подтверждённых цен или количества акций по всем классам акций компании.','Kompaniyaning barcha aksiya turlari bo‘yicha tasdiqlangan narx yoki aksiya soni yetishmaydi.','Verified prices or share counts are missing for some share classes.'],
  STALE_PRICE:['Последняя сделка слишком давняя для расчёта текущего рыночного показателя.','So‘nggi bitim joriy bozor ko‘rsatkichini hisoblash uchun juda eski.','The last trade is too old to calculate a current market ratio.'],
  DATA_CONFLICT:['Цена, количество акций и капитализация не согласуются. Данные требуют проверки.','Narx, aksiya soni va kapitallashuv bir-biriga mos emas. Tekshirish kerak.','Price, share count and capitalisation disagree and need review.'],
  HISTORICAL_MARKET_UNAVAILABLE:['Для выбранного года нет исторических рыночных данных.','Tanlangan yil uchun tarixiy bozor ma’lumotlari yo‘q.','Historical market data is unavailable for the selected year.'],
  NON_POSITIVE_PROFIT:['Для этого расчёта нужна положительная прибыль.','Bu hisob uchun musbat foyda kerak.','This calculation requires positive earnings.'],
  NON_POSITIVE_EQUITY:['Для этого расчёта нужен положительный собственный капитал.','Bu hisob uchun musbat o‘z kapitali kerak.','This calculation requires positive equity.'],
  MISSING_FINANCIALS:['В отчёте не хватает необходимых показателей.','Hisobotda kerakli ko‘rsatkichlar yetishmaydi.','Required financial figures are missing from the report.'],
  MISSING_BANK_FIELDS:['Не хватает подтверждённых строк банковского отчёта для расчёта.','Hisoblash uchun bank hisobotining tasdiqlangan satrlari yetishmaydi.','Verified bank report figures required for this calculation are missing.'],
  MISSING_CBU_DATA:['Нет данных ЦБ по этому банку за выбранный период.','Tanlangan davr uchun ushbu bank bo‘yicha MB ma’lumotlari yo‘q.','CBU data is unavailable for this bank in the selected period.'],
  WITHHELD_GROSS_UP:['Расходы на резервы почти компенсированы другими доходами. Показатель требует проверки.','Zaxira xarajatlari boshqa daromadlar bilan deyarli qoplangan. Ko‘rsatkichni tekshirish kerak.','Provision charges are nearly offset by other income. This metric needs review.'],
  UNDER_REVIEW:['Данные отчёта требуют проверки; показатель пока не публикуется.','Hisobot ma’lumotlarini tekshirish kerak; ko‘rsatkich hali e’lon qilinmaydi.','Report data needs review before this metric can be published.'],
  SOURCE_UNAVAILABLE:['Не удалось получить необходимые данные отчёта.','Hisobotning kerakli ma’lumotlarini olish imkoni bo‘lmadi.','The required report data could not be loaded.'],
  SOURCE_PENDING:['Детали отчёта загружаются. Обновите экран позже.','Hisobot tafsilotlari yuklanmoqda. Keyinroq sahifani yangilang.','Report details are being loaded. Refresh this screen later.'],
  PRICE_UNAVAILABLE:['Нет актуальной подтверждённой цены акции.','Aksiyaning tasdiqlangan joriy narxi yo‘q.','A verified current share price is unavailable.'],
  NO_RECENT_DIVIDEND:['Нет положительного дивидендного решения за последние 366 дней.','Oxirgi 366 kunda musbat dividend qarori yo‘q.','No positive dividend decision is available within the last 366 days.'],
  MISSING_VALUATION:['Недостаточно данных для оценки стоимости акции.','Aksiya qiymatini baholash uchun ma’lumot yetarli emas.','There is not enough data to estimate the share value.'],
};

export function MetricValue({row,metric,label,lang,text}) {
  if(!metricApplies(row,metric))return null;
  if(row[metric]!=null)return text;
  const reason=row.metric_reasons?.[metric];
  if(!reason)return text;
  let description=words(lang,...(reasons[reason.code]||reasons.MISSING_FINANCIALS));
  if(reason.code==='MISSING_ENDPOINT')description=words(lang,`Для расчёта роста нужна прибыль за оба года: ${reason.start} и ${reason.end}. Данных за один из них нет.`,`O‘sishni hisoblash uchun ${reason.start} va ${reason.end} yillardagi foyda kerak. Ulardan biri yo‘q.`,`Growth requires earnings for both ${reason.start} and ${reason.end}; one is missing.`);
  if(reason.code==='NON_POSITIVE_ENDPOINT')description=words(lang,`Рост не рассчитывается: прибыль за ${reason.start} или ${reason.end} год равна нулю или отрицательна.`,`O‘sish hisoblanmaydi: ${reason.start} yoki ${reason.end} yildagi foyda nol yoki manfiy.`,`Growth cannot be calculated because earnings in ${reason.start} or ${reason.end} are zero or negative.`);
  return <TermInfo termId={metric} label={`${row.ticker} · ${label}`} description={description} lang={lang} marker="—" className="terminal-missing-value"/>;
}
