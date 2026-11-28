import { useState } from 'react';

export function useVersionedDraft(value) {
  const [draft, setDraft] = useState(null);
  return {
    value: draft ? draft.value : value,
    edited: Boolean(draft),
    changed: Boolean(draft && (draft.value?.version || 0) !== (value?.version || 0)),
    edit: () => setDraft(previous => previous || { value }),
    reset: () => setDraft(null),
  };
}

export function DraftVersionNotice({ changed, reset }) {
  return changed && <div className="mkt-callout"><p>На сервере появилась новая версия.</p>
    <p>Ваши правки остаются в форме и относятся к прежней версии. Перед сохранением сравните изменения.</p>
    <button type="button" onClick={reset}>Загрузить новую версию и сбросить правки</button>
  </div>;
}

export function VersionedEditor({ value, request, children }) {
  const draft = useVersionedDraft(value);
  async function save(path, options) {
    const result = await request(path, options);
    if (result && options?.method === 'PUT') draft.reset();
    return result;
  }
  return <div onChangeCapture={draft.edit}><DraftVersionNotice {...draft} />
    <div key={draft.value?.version || 0}>{children(draft.value, save)}</div>
  </div>;
}
