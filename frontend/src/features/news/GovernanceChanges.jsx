const COPY = {
  ru: {appointed:'Назначены', departed:'Полномочия прекращены', roster:'Состав органа управления по раскрытию',
    unnamed:'Имя не раскрыто', noRole:'Должность не раскрыта'},
  en: {appointed:'Appointed', departed:'Terms ended', roster:'Governing body as disclosed',
    unnamed:'Name not disclosed', noRole:'Position not disclosed'},
  uz: {appointed:'Tayinlanganlar', departed:'Vakolatlari tugatilganlar', roster:'Oshkor etilgan boshqaruv organi tarkibi',
    unnamed:'Ism oshkor qilinmagan', noRole:'Lavozim oshkor qilinmagan'},
};

function People({rows, copy}) {
  return <ul className="ce-people">{rows.map(person => <li key={person.source_field}>
    <strong>{person.name || copy.unnamed}</strong>
    <span>{person.position || copy.noRole}</span>
    {person.work_place && <small>{person.work_place}</small>}
  </li>)}</ul>;
}

export function GovernanceChanges({governance, language}) {
  const copy = COPY[language] || COPY.ru;
  if (!governance) return null;
  return <div className="ce-governance">
    <div className="ce-governance-changes">
      {['departed', 'appointed'].map(key => governance[key]?.length > 0 &&
        <section key={key} aria-label={copy[key]}>
          <h4>{copy[key]} <span>{governance[key].length}</span></h4>
          <People rows={governance[key]} copy={copy} />
        </section>)}
    </div>
    {governance.roster?.length > 0 && <details className="ce-governance-roster">
      <summary>{copy.roster}<span>{governance.roster.length}</span></summary>
      <section aria-label={copy.roster}><People rows={governance.roster} copy={copy} /></section>
    </details>}
  </div>;
}
