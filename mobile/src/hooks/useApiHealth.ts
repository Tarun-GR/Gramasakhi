import { useCallback, useEffect, useState } from 'react';
import { fetchHealth } from '../api/client';
import { friendlyErrorMessage } from '../utils/errors';

export type ApiHealthState = 'idle' | 'loading' | 'ok' | 'error';

export function useApiHealth(autoCheck = true) {
  const [state, setState] = useState<ApiHealthState>('idle');
  const [message, setMessage] = useState<string | null>(null);

  const check = useCallback(async () => {
    setState('loading');
    setMessage(null);
    try {
      const data = await fetchHealth();
      if (data.status === 'ok') {
        setState('ok');
      } else {
        setState('error');
        setMessage('GramSakhi service is unavailable.');
      }
    } catch (err) {
      setState('error');
      setMessage(friendlyErrorMessage(err, 'Cannot reach GramSakhi right now.'));
    }
  }, []);

  useEffect(() => {
    if (autoCheck) {
      void check();
    }
  }, [autoCheck, check]);

  return { state, message, check };
}
