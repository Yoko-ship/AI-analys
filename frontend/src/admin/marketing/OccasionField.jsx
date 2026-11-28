import { Field, date } from './Widgets.jsx';

const names = { holiday: 'Праздничная подача', gaming: 'Игровой инфоповод' };
export const occasionReady = (value, evidence) => !value || evidence.some(row => row.id === value.evidence_id
  && row.version === value.evidence_version && row.status === 'verified' && row.event_at);

export function OccasionSummary({ value, evidence }) {
  if (!value) return null;
  const original = evidence.find(row => row.id === value.evidence_id && row.version === value.evidence_version);
  return <p className="mkt-muted">{names[value.kind]} · {original?.title || value.evidence_id} · версия {value.evidence_version}
    {original?.event_at && <> · дата события {date(original.event_at)} · Ташкент</>}</p>;
}

export function OccasionField({ value, onChange, evidence }) {
  const originals = evidence.filter(row => row.status === 'verified' && row.event_at);
  const selected = originals.find(row => row.id === value?.evidence_id && row.version === value?.evidence_version);
  return <div className="mkt-stack">
    <Field label="Повод и подача" help="Необязательно. Подтверждённый повод задаёт тон; факты о бирже, аудитории и рынке требуют собственных доказательств.">
      <select value={value?.kind || ''} onChange={event => onChange(event.target.value
        ? { kind: event.target.value, evidence_id: value?.evidence_id || '', evidence_version: value?.evidence_version || 0 } : null)}>
        <option value="">Обычная подача</option>{Object.entries(names).map(([kind, name]) => <option key={kind} value={kind}>{name}</option>)}
      </select>
    </Field>
    {value && <>
      <Field label="Оригинал повода" help="Сначала выберите подтверждённый оригинал с датой события в доказательствах выше. Его точная версия закрепляется за заданием и каждой языковой версией.">
        <select value={selected?.id || ''} required onChange={event => {
          const row = originals.find(original => original.id === event.target.value);
          onChange({ ...value, evidence_id: row?.id || '', evidence_version: row?.version || 0 });
        }}><option value="">Выберите оригинал с датой</option>{originals.map(row => <option key={row.id} value={row.id}>{row.title} · v{row.version}</option>)}</select>
      </Field>
      {value.evidence_id && !selected && <p className="mkt-callout">Оригинал не выбран или его версия изменилась. Проверьте доказательства и выберите его заново.</p>}
      <OccasionSummary value={selected ? value : null} evidence={evidence} />
      <p className="mkt-muted">{value.kind === 'holiday'
        ? 'Спокойная памятка или полезное напоминание. Праздничная дата сама по себе не подтверждает часы работы или закрытие биржи.'
        : 'Собственный объясняющий образ и другая подача. Игровой релиз сам по себе не подтверждает популярность или влияние на акции. Чужие изображения и музыка требуют прав.'}</p>
    </>}
  </div>;
}
