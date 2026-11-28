import { useEffect, useRef } from 'react';

export function useSocialCallback(request, loaded) {
  const callback = useRef(null);
  const started = useRef(false);
  useEffect(() => {
    const url = new URL(window.location.href);
    if (!callback.current && url.searchParams.has('state') && (url.searchParams.has('code') || url.searchParams.has('error'))) {
      callback.current = { state: url.searchParams.get('state'), code: url.searchParams.get('code'), error: url.searchParams.get('error') };
      for (const key of ['state', 'code', 'error', 'error_description', 'error_reason']) url.searchParams.delete(key);
      url.searchParams.set('marketing', 'settings');
      window.history.replaceState(window.history.state, '', url);
    }
    // Finish only after the initial workspace read so it cannot overwrite the
    // connected account. The ref also prevents a duplicate exchange in StrictMode.
    if (!loaded || !callback.current || started.current) return;
    started.current = true;
    const provider = callback.current.state.startsWith('meta_') ? 'meta' : 'linkedin';
    request(`/oauth/${provider}/finish`, { method: 'POST', body: callback.current,
      message: provider === 'meta' ? 'Вход завершён. Выберите целевой аккаунт Meta.' : 'Личный профиль подключён. Правила выпуска сохранили прежние разрешения.' });
    callback.current = null;
  }, [loaded, request]);
}
