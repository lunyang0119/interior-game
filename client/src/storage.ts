/** localStorage: accounts: [{id, token}], active_id. */

export interface Account { id: string; token: string }

const KEY_ACCOUNTS = "accounts";
const KEY_ACTIVE = "active_id";

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch { /* private mode etc. */ }
}

export function accounts(): Account[] {
  return read<Account[]>(KEY_ACCOUNTS, []);
}

export function activeId(): string | null {
  return read<string | null>(KEY_ACTIVE, null);
}

export function activeAccount(): Account | null {
  const id = activeId();
  return accounts().find((a) => a.id === id) ?? accounts()[0] ?? null;
}

export function setActive(id: string): void {
  write(KEY_ACTIVE, id);
}

export function addAccount(acct: Account, makeActive = true): void {
  const list = accounts().filter((a) => a.id !== acct.id);
  list.push(acct);
  write(KEY_ACCOUNTS, list);
  if (makeActive) setActive(acct.id);
}

export function updateToken(id: string, token: string): void {
  write(KEY_ACCOUNTS, accounts().map((a) => (a.id === id ? { id, token } : a)));
}

export function removeAccount(id: string): void {
  const list = accounts().filter((a) => a.id !== id);
  write(KEY_ACCOUNTS, list);
  if (activeId() === id) write(KEY_ACTIVE, list[0]?.id ?? null);
}

/** Returns the ?t= token from the URL (if any) and strips it from the address bar. */
export function takeRecoveryToken(): string | null {
  const url = new URL(location.href);
  const t = url.searchParams.get("t");
  if (!t) return null;
  url.searchParams.delete("t");
  history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
  return t;
}

export function recoveryLink(token: string): string {
  const url = new URL(location.href);
  url.search = "";
  url.hash = "";
  url.searchParams.set("t", token);
  return url.toString();
}
