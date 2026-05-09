import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export type SessionUser = {
  id?: string;
  email?: string;
  full_name?: string;
  role?: string;
};

type SessionState = {
  accessToken: string | null;
  refreshToken: string | null;
  user: SessionUser | null;
  hydrated: boolean;
};

const KEY_ACCESS = 'access_token';
const KEY_REFRESH = 'refresh_token';
const KEY_USER = 'current_user';

async function readItem(key: string) {
  if (Platform.OS === 'web') return localStorage.getItem(key);
  return SecureStore.getItemAsync(key);
}

async function writeItem(key: string, value: string) {
  if (Platform.OS === 'web') {
    localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

async function deleteItem(key: string) {
  if (Platform.OS === 'web') {
    localStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

let state: SessionState = {
  accessToken: null,
  refreshToken: null,
  user: null,
  hydrated: false,
};

let hydrated = false;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

export function subscribeSession(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getSessionState() {
  return state;
}

export async function hydrateSession() {
  if (hydrated) return getSessionState();
  const [accessToken, refreshToken, rawUser] = await Promise.all([
    readItem(KEY_ACCESS),
    readItem(KEY_REFRESH),
    readItem(KEY_USER),
  ]);

  state = {
    accessToken: accessToken || null,
    refreshToken: refreshToken || null,
    user: rawUser ? JSON.parse(rawUser) : null,
    hydrated: true,
  };
  hydrated = true;
  notify();
  return getSessionState();
}

export async function setSession(next: { access_token?: string; refresh_token?: string; user?: SessionUser | null }) {
  state = {
    accessToken: next.access_token || null,
    refreshToken: next.refresh_token || null,
    user: next.user || null,
    hydrated: true,
  };

  await Promise.all([
    writeItem(KEY_ACCESS, state.accessToken || ''),
    writeItem(KEY_REFRESH, state.refreshToken || ''),
    writeItem(KEY_USER, JSON.stringify(state.user || null)),
  ]);

  hydrated = true;
  notify();
}

export async function clearSession() {
  state = {
    accessToken: null,
    refreshToken: null,
    user: null,
    hydrated: true,
  };

  await Promise.all([
    deleteItem(KEY_ACCESS),
    deleteItem(KEY_REFRESH),
    deleteItem(KEY_USER),
  ]);

  hydrated = true;
  notify();
}
