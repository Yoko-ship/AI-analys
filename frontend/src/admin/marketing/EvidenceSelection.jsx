import { Status } from './Widgets.jsx';

export function EvidenceSelection({ evidence, selected, onChange, claims = [] }) {
  return <fieldset><legend>Доказательства и используемые факты</legend>
    {!evidence.length && <p>Сначала импортируйте оригиналы в разделе «Источники».</p>}
    {evidence.map(ev => <div className="mkt-item" key={ev.id}>
      <label className="mkt-checkbox"><input type="checkbox" checked={selected.includes(ev.id)} onChange={e => onChange(e.target.checked ? [...selected, ev.id] : selected.filter(id => id !== ev.id))} />{ev.title}</label>
      <p><Status value={ev.status} /> · {ev.publisher}</p>
      {selected.includes(ev.id) && <div className="mkt-checks">{Object.entries(ev.data).filter(([, value]) => ['number', 'string'].includes(typeof value)).map(([field, value]) => {
        const claim = { evidence_id: ev.id, field, value, unit: ev.units[field] || '' };
        return <label key={field}><input type="checkbox" name="claims" value={JSON.stringify(claim)} defaultChecked={claims.some(c => c.evidence_id === ev.id && c.field === field)} />{field} · {String(value)} {claim.unit}</label>;
      })}</div>}
    </div>)}
  </fieldset>;
}
