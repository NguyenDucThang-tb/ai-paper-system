import { useEffect, useSyncExternalStore } from 'react';

import { getSessionState, hydrateSession, subscribeSession } from './session';

export function useSession() {
  const snapshot = useSyncExternalStore(subscribeSession, getSessionState, getSessionState);

  useEffect(() => {
    hydrateSession();
  }, []);

  return snapshot;
}
