import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMediaQuery } from '../../shared/useMediaQuery.js';
import './ratingPrompt.css';

const NEXT_PROMPT = 'uz_rating_next_at';
const SESSION_SEEN = 'uz_rating_seen';
const DAY = 86400000;
const EDITING = 'input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],[role="combobox"],[role="slider"],[role="spinbutton"],[role="grid"]';

function cooldownUntil() {
  try {
    const value = Number(localStorage.getItem(NEXT_PROMPT));
    return Number.isFinite(value) ? value : 0;
  } catch { return 0; }
}
function alreadyAsked() {
  try { return sessionStorage.getItem(SESSION_SEEN) === '1'; } catch { return false; }
}
function snooze(days) {
  try { localStorage.setItem(NEXT_PROMPT, String(Math.max(cooldownUntil(), Date.now() + days * DAY))); } catch { /* Storage is optional. */ }
  try { sessionStorage.setItem(SESSION_SEEN, '1'); } catch { /* Keep the in-memory state. */ }
}
function interrupted() {
  return document.hidden || !!document.fullscreenElement
    || document.body.classList.contains('terminal-panel-fullscreen')
    || !!document.activeElement?.closest(EDITING)
    || [...document.querySelectorAll('dialog[open],[aria-modal="true"]')].some(el => el.getClientRects().length)
    || document.body.style.overflow === 'hidden';
}

export function RatingPrompt({ language, blocked }) {
  const touchLayout = useMediaQuery('(max-width: 760px), (pointer: coarse)');
  const tx = (ru, uz, en) => language === 'uz' ? uz : language === 'en' ? en : ru;
  const [phase, setPhase] = useState('waiting');
  const [suspended, setSuspended] = useState(false);
  const phaseRef = useRef('waiting');
  const blockedRef = useRef(blocked);
  blockedRef.current = blocked;
  const root = useRef(null);
  const submission = useRef(null);
  const controller = useRef(null);
  const alive = useRef(true);
  const transition = useCallback(next => { phaseRef.current = next; setPhase(next); }, []);
  const dismiss = useCallback(() => { snooze(7); transition('closed'); }, [transition]);

  useEffect(() => {
    alive.current = true;
    const delay = 90000 + Math.random() * 90000;
    let elapsed = 0, lastTick = Date.now(), interactions = 0;
    const interact = event => {
      if (!blockedRef.current && !document.hidden && !root.current?.contains(event.target)) interactions += 1;
    };
    const tick = () => {
      const now = Date.now();
      const pause = blockedRef.current || interrupted();
      setSuspended(pause);
      if (!pause && phaseRef.current === 'waiting') {
        elapsed += Math.max(0, now - lastTick);
        if (elapsed >= delay && interactions >= 2 && now >= cooldownUntil() && !alreadyAsked()) {
          // Claim the prompt when shown, so reloads and other tabs do not nag.
          snooze(7);
          transition('ask');
        }
      }
      lastTick = now;
    };
    // Focus and visibility boundaries must not charge a hidden/typing interval
    // to active reading time when the next timer eventually runs.
    const boundary = () => { lastTick = Date.now(); setSuspended(blockedRef.current || interrupted()); };
    const timer = setInterval(tick, 1000);
    document.addEventListener('pointerdown', interact);
    document.addEventListener('keydown', interact);
    document.addEventListener('visibilitychange', boundary);
    document.addEventListener('focusin', boundary);
    document.addEventListener('focusout', boundary);
    document.addEventListener('fullscreenchange', boundary);
    return () => {
      alive.current = false;
      controller.current?.abort();
      clearInterval(timer);
      document.removeEventListener('pointerdown', interact);
      document.removeEventListener('keydown', interact);
      document.removeEventListener('visibilitychange', boundary);
      document.removeEventListener('focusin', boundary);
      document.removeEventListener('focusout', boundary);
      document.removeEventListener('fullscreenchange', boundary);
    };
  }, [transition]);

  const send = useCallback(async rating => {
    if (!['ask', 'error'].includes(phaseRef.current)) return;
    if (!submission.current) submission.current = {
      response_id: crypto.randomUUID(), rating, language,
      page_path: window.location.pathname.slice(0, 240),
    };
    transition('sending');
    controller.current = new AbortController();
    const timeout = setTimeout(() => controller.current?.abort(), 15000);
    try {
      const response = await fetch('/api/feedback/ratings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'omit', body: JSON.stringify(submission.current), signal: controller.current.signal,
      });
      const result = await response.json();
      if (!response.ok || result.ok !== true) throw new Error('Rating not saved');
      if (alive.current) {
        snooze(30);
        if (phaseRef.current !== 'closed') transition('thanks');
      }
    } catch {
      if (alive.current && phaseRef.current !== 'closed') transition('error');
    } finally { clearTimeout(timeout); }
  }, [language, transition]);

  useEffect(() => {
    if (phase !== 'thanks') return undefined;
    const timer = setTimeout(() => transition('closed'), 4000);
    return () => clearTimeout(timer);
  }, [phase, transition]);

  useEffect(() => {
    if (blocked || suspended || !['ask', 'sending', 'error', 'thanks'].includes(phase)) return undefined;
    const keydown = event => {
      if (event.defaultPrevented || event.repeat || event.isComposing || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || interrupted()) return;
      // Never steal digits from another control, including custom chart widgets.
      if (event.target !== document.body && !root.current?.contains(event.target)) return;
      if (event.key === 'Escape') { event.preventDefault(); dismiss(); }
      if (phaseRef.current === 'ask' && /^[123]$/.test(event.key)) { event.preventDefault(); send(Number(event.key)); }
    };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, [blocked, suspended, phase, dismiss, send]);

  if (blocked || suspended || phase === 'waiting' || phase === 'closed') return null;
  const title = tx('Как вам UZStock?', 'UZStock sizga qanday?', 'How is UZStock?');
  const labels = [touchLayout ? tx('Не очень', 'Uncha emas', 'Needs work') : tx('Есть проблемы', 'Yaxshilash kerak', 'Needs work'), tx('Нормально', 'Qoniqarli', 'Okay'), tx('Отлично', 'Ajoyib', 'Great')];
  return createPortal(<aside ref={root} className="rating-prompt" role="region" aria-label={title} aria-live="polite">
    <button className="rating-dismiss" type="button" onClick={dismiss} aria-label={tx('Закрыть оценку', 'Baholashni yopish', 'Dismiss rating')}>×</button>
    <div className="rating-heading">
      <span className="rating-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 3v-3H3V6a2 2 0 0 1 2-2Z"/><path d="M8 9h8M8 13h5"/></svg></span>
      <div><h2>{title}</h2>
        {phase === 'ask' && <p className="rating-instruction">{touchLayout
          ? tx('Нажмите на ответ', 'Javobni bosing', 'Tap an answer')
          : tx('Нажмите 1, 2 или 3 · Esc — закрыть', '1, 2 yoki 3 · Esc — yopish', 'Press 1, 2 or 3 · Esc to close')}</p>}
      </div>
    </div>
    {phase === 'ask' && <>
      <div className="rating-choices">
        {labels.map((label, index) => <button key={index} type="button" className="rating-choice" onClick={() => send(index + 1)} aria-keyshortcuts={touchLayout ? undefined : String(index + 1)}>
          {!touchLayout && <kbd className="rating-number" aria-hidden="true">{index + 1}</kbd>}
          <svg className="rating-face" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9"/><path d="M8.5 9h.01M15.5 9h.01" strokeWidth="2.5"/>
            <path d={['M8 15q4-5 8 0', 'M8 14h8', 'M8 13q4 5 8 0'][index]}/>
          </svg>
          <span className="rating-label">{label}</span>
        </button>)}
      </div>
    </>}
    {phase === 'sending' && <p className="rating-message" role="status">{tx('Сохраняем…', 'Saqlanmoqda…', 'Saving…')}</p>}
    {phase === 'thanks' && <p className="rating-message" role="status">{tx('Спасибо за оценку!', 'Bahoyingiz uchun rahmat!', 'Thanks for your rating!')}</p>}
    {phase === 'error' && <>
      <p className="rating-message" role="alert">{tx('Не удалось сохранить оценку. Попробуйте ещё раз.', 'Baho saqlanmadi. Qayta urinib ko‘ring.', 'Your rating was not saved. Please try again.')}</p>
      <button type="button" className="secondary-btn rating-retry" onClick={() => send(submission.current.rating)}>{tx('Повторить', 'Qayta urinish', 'Retry')}</button>
    </>}
  </aside>, document.body);
}
