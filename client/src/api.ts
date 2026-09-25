import type { AvatarLook, Chars, Item, Room, RoomItem } from "./catalog";
import { state, type Contribution } from "./state";

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

const MESSAGES: Record<string, string> = {
  unauthorized: "로그인이 필요해요",
  rate_limited: "잠시만 기다린 뒤 다시 시도해주세요....(10분이 이상적)",
  not_in_sheet: "시트에 없는 ID네요",
  already_registered: "이미 등록된 ID에요 (복구 링크로 들어와주세요)",
  sheet_unavailable: "시트에 연결이 안되었어요. 오류니 잠시 뒤, 다시 한 번 들어와주세요.",
  ambiguous_nickname: "닉네임이 겹쳐요. 다른 걸로 써주세요",
  nickname_taken: "그 닉네임은 이미 다른 ID로 등록됐어요",
  unknown_item: "없는 아이템이에요",
  out_of_bounds: "마크로 치자면 파랜드에요. 더 이상 갈 수 없어요.",
  bad_cell_type: "여기엔 못 놓아요",
  collision: "이미 무언가 있어요",
  needs_surface: "테이블 등의 위에만 놓을 수 있어요",
  surface_occupied: "그 자리엔 이미 뭐가 올라가 있어요",
  spans_multiple_surfaces: "한 가구 위에만 놓을 수 있어요",
  insufficient_funds: "돈이 부족해요. 재화를 번 뒤 다시 구입해주세요",
  has_children: "위에 올린 걸 먼저 치운 다음 다시 시도해주세요",
  not_found: "이미 없어진 아이템이에요",
  network: "네트워크 오류네요",
};

export function msgFor(code: string): string {
  return MESSAGES[code] ?? code;
}

async function call<T>(method: string, path: string, body?: unknown, extra: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { ...extra };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network");
  }
  if (res.status === 304) return null as T;
  if (!res.ok) {
    let code = `http_${res.status}`;
    try {
      code = (await res.json()).error ?? code;
    } catch { /* ignore */ }
    throw new ApiError(res.status, code);
  }
  return (await res.json()) as T;
}

export interface MeResponse { id: string; balance: number; contributions: Contribution[]; avatar: AvatarLook }
export interface RoomResponse { version: number; items: RoomItem[] }

export const api = {
  catalog: () => call<{ items: Item[]; room: Room; chars: Chars }>("GET", "/api/catalog"),
  register: (id: string) => call<{ id: string; token: string; created: boolean; name: string; earned: number }>("POST", "/api/register", { id }),
  me: () => call<MeResponse>("GET", "/api/me"),
  sync: () => call<{ refreshed: boolean; balance: number; contributions: Contribution[] }>("POST", "/api/sync"),
  putAvatar: (a: AvatarLook) => call<{ avatar: AvatarLook }>("PUT", "/api/avatar", a),
  room: (etagVersion?: number) =>
    call<RoomResponse | null>("GET", "/api/room", undefined,
      etagVersion === undefined || etagVersion < 0 ? {} : { "If-None-Match": `"${etagVersion}"` }),
  place: (item_id: string, x: number, y: number) =>
    call<{ uid: number; balance: number; version: number }>("POST", "/api/room/place", { item_id, x, y }),
  move: (uid: number, x: number, y: number) => call<{ uid: number; version: number }>("POST", "/api/room/move", { uid, x, y }),
  remove: (uid: number) => call<{ balance: number; version: number }>("DELETE", `/api/room/item/${uid}`),
  rotate: () => call<{ id: string; token: string }>("POST", "/api/token/rotate"),
  logins: () => call<{ logins: { ts: number; action: string; ip_hash: string; ua: string; ok: number }[] }>("GET", "/api/me/logins"),
  /** Verify a token without touching global state. */
  meWith: async (token: string): Promise<MeResponse> => {
    const res = await fetch("/api/me", { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new ApiError(res.status, "unauthorized");
    return (await res.json()) as MeResponse;
  },
};
