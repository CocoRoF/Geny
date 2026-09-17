/**
 * What the app remembers between launches.
 *
 * The token goes in the OS keystore (`expo-secure-store`) — it is a 30-day
 * credential to a server that can run shell commands, and AsyncStorage is a
 * plaintext file any backup picks up. Everything else (the address, the last
 * session) is a preference and lives in AsyncStorage, which has no size or
 * availability caveats.
 *
 * SecureStore can be unavailable (a device with no lock screen, an emulator
 * image without a keystore). Falling back to AsyncStorage there is the right
 * trade: the alternative is an app that cannot sign in at all.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

const TOKEN_KEY = 'geny_auth_token';
const BASE_URL_KEY = 'geny_server_url';
const SESSION_KEY = 'geny_last_session';

export async function loadToken(): Promise<string | null> {
  try {
    const secure = await SecureStore.getItemAsync(TOKEN_KEY);
    if (secure) return secure;
  } catch {
    /* no keystore on this device — fall through */
  }
  try {
    return await AsyncStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function saveToken(token: string | null): Promise<void> {
  if (token === null) {
    await Promise.allSettled([
      SecureStore.deleteItemAsync(TOKEN_KEY),
      AsyncStorage.removeItem(TOKEN_KEY),
    ]);
    return;
  }
  try {
    await SecureStore.setItemAsync(TOKEN_KEY, token);
    // Never leave a copy behind in the plaintext store once the keystore took
    // it — a fallback that lingers is a leak with no expiry.
    await AsyncStorage.removeItem(TOKEN_KEY).catch(() => undefined);
    return;
  } catch {
    await AsyncStorage.setItem(TOKEN_KEY, token);
  }
}

export async function loadBaseUrl(): Promise<string> {
  try {
    return (await AsyncStorage.getItem(BASE_URL_KEY)) ?? '';
  } catch {
    return '';
  }
}

export async function saveBaseUrl(url: string): Promise<void> {
  await AsyncStorage.setItem(BASE_URL_KEY, url).catch(() => undefined);
}

export async function loadLastSession(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

export async function saveLastSession(sessionId: string | null): Promise<void> {
  if (!sessionId) {
    await AsyncStorage.removeItem(SESSION_KEY).catch(() => undefined);
    return;
  }
  await AsyncStorage.setItem(SESSION_KEY, sessionId).catch(() => undefined);
}
