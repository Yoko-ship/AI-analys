import React from 'react';

const COPY = {
  ru: { body: 'Дата собрания взята из текста объявления.', conflict: 'Она отличается от даты в полях OpenInfo; дата публикации сохранена отдельно.', ambiguous: 'В тексте указаны противоречивые даты собрания. Дата требует проверки.' },
  en: { body: 'The meeting date comes from the announcement text.', conflict: 'It differs from the OpenInfo metadata; the publication date is preserved separately.', ambiguous: 'The text contains conflicting meeting dates. The date requires review.' },
  uz: { body: 'Yig‘ilish sanasi e’lon matnidan olindi.', conflict: 'U OpenInfo maydonidagi sanadan farq qiladi; e’lon sanasi alohida saqlangan.', ambiguous: 'Matnda yig‘ilish sanalari bir-biriga zid. Sanani tekshirish kerak.' },
};
export function SourceDateEvidence({ document, language }) {
  const tx = COPY[language] || COPY.ru;
  if (!document.date_evidence && !document.date_conflict) return null;
  return <section className="ce-date-evidence">
    <p>{document.date_evidence && !document.date_unresolved ? <>{tx.body} {document.date_conflict ? tx.conflict : ''}</> : tx.ambiguous}</p>
    {document.date_evidence && <blockquote>{document.date_evidence}</blockquote>}
  </section>;
}
