import React from 'react';
import { portfolioError } from './copy.js';

export function tashkentDate() {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tashkent', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const part = type => parts.find(p => p.type === type).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export function TransactionForm({ transaction, instruments, apiFetch, text, onCancel, onSaved, beginMutation, endMutation }) {
  const [form, setForm] = React.useState(() => ({
    ticker: transaction?.ticker || '', kind: transaction?.kind || 'buy',
    trade_date: transaction?.trade_date || tashkentDate(), quantity: String(transaction?.quantity ?? ''),
    price: String(transaction?.price ?? ''), fees: String(transaction?.fees ?? '0'),
    amount: String(transaction?.amount ?? ''), note: transaction?.note || '',
  }));
  const [key] = React.useState(() => crypto.randomUUID());
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');
  const ticker = React.useRef(null);
  const busy = React.useRef(false);
  React.useEffect(() => { ticker.current?.focus(); }, []);
  const field = name => ({ value: form[name], onChange: e => setForm(prev => ({ ...prev, [name]: e.target.value })) });
  const opening = form.kind === 'opening';
  const dividend = form.kind === 'dividend';
  const submit = async event => {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    setSaving(true); setError(''); beginMutation();
    const payload = { ...form, ticker: form.ticker.trim().toUpperCase(),
      trade_date: opening ? null : form.trade_date, quantity: dividend ? '0' : form.quantity,
      price: dividend ? '0' : form.price, fees: opening ? '0' : (form.fees || '0'), amount: dividend ? form.amount : '0',
      ...(transaction ? { version: transaction.version } : { id: key }),
    };
    try {
      const response = await apiFetch(transaction ? `/api/portfolio/transactions/${encodeURIComponent(transaction.id)}` : '/api/portfolio/transactions', {
        method: transaction ? 'PUT' : 'POST', body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.ok) throw new Error(portfolioError(response, body, text));
      await onSaved();
    } catch (err) { setError(err.message || text('failed')); }
    finally { endMutation(); busy.current = false; setSaving(false); }
  };
  return <article className="portfolio-form panel" aria-labelledby="portfolio-form-title">
    <h2 id="portfolio-form-title">{text(transaction ? 'editTitle' : 'record')}</h2>
    <form onSubmit={submit} onKeyDown={e => { if (e.key === 'Escape' && !saving) onCancel(); }}>
      <fieldset disabled={saving}>
        <div className="portfolio-form-grid">
          <label className="field"><span>{text('kind')}</span><select {...field('kind')}>
            {['buy', 'sell', 'dividend', 'opening'].map(kind => <option value={kind} key={kind}>{text(kind)}</option>)}
          </select></label>
          <label className="field"><span>{text('ticker')}</span><input ref={ticker} required list="portfolio-instruments" maxLength={40} autoComplete="off" placeholder="AGBA" {...field('ticker')} /></label>
          <datalist id="portfolio-instruments">{instruments.map(item => <option key={item.ticker} value={item.ticker}>{item.name}</option>)}</datalist>
          {!opening && <label className="field"><span>{text('tradeDate')}</span><input required type="date" min="1900-01-01" max={tashkentDate()} {...field('trade_date')} /></label>}
          {dividend ? <label className="field"><span>{text('amount')}</span><input required type="number" min="0.000001" max="1000000000000" step="0.000001" {...field('amount')} /></label> : <>
            <label className="field"><span>{text('quantity')}</span><input required type="number" min="0.000001" max="1000000000000" step="0.000001" {...field('quantity')} /></label>
            <label className="field"><span>{text(opening ? 'openingPrice' : 'price')}</span><input required type="number" min="0" max="1000000000000" step="0.000001" {...field('price')} /></label>
          </>}
          {!opening && <label className="field"><span>{text('fees')}</span><input type="number" min="0" max="1000000000000" step="0.000001" {...field('fees')} /></label>}
          <label className="field portfolio-note"><span>{text('note')}</span><input maxLength={1000} {...field('note')} /></label>
        </div>
        {(opening || dividend) && <p className="muted">{text(opening ? 'openingHelp' : 'dividendHelp')}</p>}
        {error && <p className="portfolio-error" role="alert">{error}</p>}
        <div className="portfolio-actions"><button type="submit" className="primary-btn">{text(saving ? 'saving' : 'save')}</button><button type="button" className="secondary-btn" onClick={onCancel}>{text('cancel')}</button></div>
      </fieldset>
    </form>
  </article>;
}
