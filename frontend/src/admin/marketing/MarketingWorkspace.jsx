import { useLayoutEffect, useRef, useState } from 'react';
import { useMarketing } from './useMarketing.js';
import { Dialog, History, Panel, Status, date, number } from './Widgets.jsx';
import { GoalSection } from './GoalSection.jsx';
import { SettingsSection } from './SettingsSection.jsx';
import { SourcesSection } from './SourcesSection.jsx';
import { ContentSection } from './ContentSection.jsx';
import { WorkflowSection } from './WorkflowSection.jsx';
import { ReportsSection } from './ReportsSection.jsx';
import { ExperimentsSection } from './ExperimentsSection.jsx';
import { connectionStatus } from './ChannelConnection.jsx';
import { useSocialCallback } from './useSocialCallback.js';
import { RecoveryPanel } from './RecoveryPanel.jsx';
import { TelegramNews } from './TelegramNews.jsx';
import './marketing.css';

const tabs = [['overview', 'Обзор команды'], ['goal', 'Цель и стратегия'], ['sources', 'Источники'], ['content', 'Контент и очередь'], ['workflow', 'Рабочий цикл'], ['experiments', 'Эксперименты'], ['reports', 'Отчёты'], ['settings', 'Настройки']];

export default function MarketingWorkspace({ apiFetch }) {
  const { data, error, notice, busy, sync, request, readFile, downloadFile } = useMarketing(apiFetch);
  const [tab, setTab] = useState(() => {
    const query = new URLSearchParams(window.location.search);
    return query.has('state') ? 'settings' : query.get('marketing') || 'overview';
  });
  const [dialog, setDialog] = useState(null);
  const navRef = useRef(null);
  const loaded = Boolean(data);
  useSocialCallback(request, loaded);
  useLayoutEffect(() => {
    const nav = navRef.current;
    const current = nav?.querySelector('[aria-current="page"]');
    if (!current) return;
    const bounds = nav.getBoundingClientRect();
    const button = current.getBoundingClientRect();
    if (button.left < bounds.left) nav.scrollLeft += button.left - bounds.left;
    else if (button.right > bounds.right) nav.scrollLeft += button.right - bounds.right;
  }, [tab, loaded]);
  function navigate(next) {
    const url = new URL(window.location.href);
    url.searchParams.set('marketing', next);
    window.history.replaceState(window.history.state, '', url);
    setTab(next);
  }
  async function onHistory(kind, id, title) {
    const result = await request(`/history/${kind}/${id}`);
    if (result) setDialog({ title, body: <History items={result.items} /> });
  }
  if (!data) return <div className="ai-marketing-workspace" aria-busy={!error}>{error ? <div role="alert">{error}<button onClick={() => request('/workspace', { refresh: true })}>Повторить загрузку</button></div> : <p role="status">Загрузка маркетинговой команды…</p>}</div>;
  const goal = data.active_goal;
  const counts = [
    ['Материалов', data.candidates.length], ['Проверено', data.candidates.filter(c => c.check?.passed).length],
    ['В очереди', data.deliveries.filter(d => ['scheduled', 'retry', 'sending'].includes(d.status)).length],
    ['Опубликовано', data.deliveries.filter(d => d.status === 'published').length],
  ];
  const props = { data, busy, error, request, onHistory, readFile, downloadFile };
  return <section className="ai-marketing-workspace" aria-label="ИИ-маркетинг">
    <div className="mkt-topline"><span>UZStock / ИИ-маркетинг</span><span>Asia/Tashkent{data.pause.publications ? ' · Публикации на паузе' : ''}</span></div>
    <nav ref={navRef} className="mkt-nav" aria-label="Разделы маркетинга">{tabs.map(([id, label]) => <button type="button" key={id} aria-current={tab === id ? 'page' : undefined} onClick={() => navigate(id)}>{label}</button>)}</nav>
    <div className="mkt-title"><h2>{tabs.find(([id]) => id === tab)?.[1] || 'Обзор команды'}</h2><span className="mkt-muted">Кабинет владельца</span></div>
    <section className="mkt-row mkt-between" aria-label="Обновление состояния">
      <p className="mkt-muted">{sync.updatedAt ? `Обновлено ${new Date(sync.updatedAt).toLocaleTimeString('ru-RU', { timeZone: 'Asia/Tashkent' })} · Ташкент` : 'Состояние загружается'} · обновляется автоматически</p>
      {sync.error && <div className="mkt-callout"><p role="status">Автообновление недоступно. Показаны последние загруженные данные. {sync.error}</p><button disabled={busy} onClick={() => request('/workspace')}>Обновить состояние</button></div>}
    </section>
    <div id="marketing-error" role={error ? 'alert' : undefined} className={error ? 'mkt-error' : undefined}>{error}</div>
    <div role="status" className={notice ? 'mkt-notice' : undefined}>{notice}</div>
    <RecoveryPanel {...props} />
    {tab === 'overview' && <>
      <TelegramNews {...props} navigate={navigate} />
      {goal && <div className="mkt-goal"><div><span className="mkt-kicker">ДЕЙСТВУЮЩАЯ ЦЕЛЬ</span><h3>{goal.title}</h3><p>{number(goal.target)} {goal.unit} · до {date(goal.deadline)} · бюджет {number(goal.budget)} {goal.currency}</p></div><button onClick={() => navigate('goal')}>Открыть цель</button></div>}
      <div className="mkt-kpis">{counts.map(([label, value]) => <div key={label}><span>{label}</span><strong>{number(value)}</strong></div>)}</div>
      <div className="mkt-columns"><Panel title="Команда и задачи"><div className="mkt-roles">{data.roles.map(role => <button className="mkt-role" key={role.id} onClick={() => setDialog({ title: role.name, body: <><p>{role.purpose}</p><p>Передаёт результат: {role.recipient}</p><h4>Задачи</h4>{data.tasks.filter(t => t.role === role.id).map(t => <p key={t.id}>{t.title} · <Status value={t.status} /></p>)}{!data.tasks.some(t => t.role === role.id) && <p className="mkt-muted">Активных задач пока нет.</p>}</> })}><span className="mkt-role-mark" aria-hidden="true">{role.name.slice(0, 2)}</span><span><strong>{role.name}</strong><small>{role.purpose}</small></span></button>)}</div></Panel>
        <div className="mkt-stack"><Panel title="Расширенная работа"><p>Цели, стратегии и другие площадки настраиваются отдельно. Для новостей в Telegram они не нужны.</p><button onClick={() => navigate('goal')}>Открыть планирование</button></Panel>
          <Panel title="Площадки">{data.platforms.map(platform => <div className="mkt-item mkt-row mkt-between" key={platform.id}><span>{platform.name}</span><Status value={connectionStatus(data, data.accounts.find(a => a.platform === platform.id))} /></div>)}</Panel>
          <Panel title="Результат бизнеса"><p className="mkt-muted">{goal?.baseline == null ? 'Нет измеренной базы для сравнения с целью.' : `Исходная база: ${number(goal.baseline)} ${goal.unit}.`}</p><p>Работа команды и подтверждённые публикации учитываются отдельно от посещений, регистраций и продаж.</p></Panel></div></div>
    </>}
    {tab === 'goal' && <GoalSection {...props} />}
    {tab === 'settings' && <SettingsSection {...props} />}
    {tab === 'sources' && <SourcesSection {...props} />}
    {tab === 'content' && <ContentSection {...props} />}
    {tab === 'workflow' && <WorkflowSection {...props} />}
    {tab === 'reports' && <ReportsSection {...props} />}
    {tab === 'experiments' && <ExperimentsSection {...props} />}
    {dialog && <Dialog title={dialog.title} onClose={() => setDialog(null)}>{dialog.body}</Dialog>}
  </section>;
}
