import type { AvatarLook, RawCatalog, RoomItem } from "./catalog";
import { state, type Contribution } from "./state";

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

const MESSAGES: Record<string, string> = {
  unauthorized: "로그인이 필요해요",
  rate_limited: "요청이 너무 잦아요. 잠시 후 다시 시도해주세요",
  not_in_sheet: "시트에 없는 ID네요",
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
  bad_span: "벽지 폭이 이상해요",
  not_for_sale: "파는 물건이 아니에요",
  fixed_item: "이건 방의 일부라 손댈 수 없어요",
  unknown_room: "없는 방이에요",
  fish_cooldown: "잠깐 쉬었다가 다시 던져요",
  too_early: "아직 입질이 안 끝났어요",
  no_session: "낚싯대를 먼저 던져요",
  room_locked: "아직 들어갈 수 없는 곳이에요",
  nothing_to_deliver: "지금은 납품할 곳이 없어요",
  deliver_expired: "너무 늦었어요. 이 물고기는 이미 팔렸어요",
  already_delivered: "이미 납품한 물고기예요",
  not_your_catch: "내가 낚은 물고기만 납품할 수 있어요",
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
export interface RoomResponse { room: string; version: number; items: RoomItem[]; ruined: number }
/** One need of a room's current restoration stage (server restore.py NeedProgress.public()). */
export interface NeedProgress { type: "ruined_zero" | "placed" | "deliver" | "pool"; label: string; have: number; want: number; done: boolean }
export interface StageProgress { id: string; name: string; done: boolean; unlocks: string[]; needs: NeedProgress[] }
/** A room's restoration: completed count, total, and the current stage (null once everything is done). */
export interface RoomProgress { stage: number; total: number; done: boolean; current: StageProgress | null }
/** A pending reservation: a guest who wants `item_id` (kind "item") or the monthly dog lover (kind "dog"). */
export interface ReservationView { id: number; kind: "item" | "dog"; item_id: string | null; due_day: number; days_left: number }
/** A room's comfort (server comfort.py) and tonight's expected guests (guests.py room_view). Absent for locked rooms. */
export interface ComfortView {
  score: number; beds: number; raw: number; base: number; mult: number; set: string | null; set_share: number;
  ruined: number; affection: number; guests: number; per_guest: number; pay: number; skipped: boolean;
  reservation: ReservationView | null;
}
export interface RoomSummary {
  id: string; name: string; version: number; ruined: number; online: number; progress: RoomProgress | null;
  comfort: ComfortView | null;
}
export interface RoomsResponse { rooms: RoomSummary[]; locked: string[] }
/** A room's current stage wants this catch: where, and how far along it is. */
export interface Deliverable { room: string; name: string; have: number; want: number }
export interface FishFinishResponse {
  ok: boolean; pulls: number; escaped: boolean; id: string; name: string; value: number; balance: number;
  seq: number | null; deliverable: Deliverable[];
}
/** One row of the activity log (server events table). amount = change of the shared pool, + means it grew. */
export interface ActivityEvent {
  seq: number; ts: number;
  kind: "place" | "remove" | "sell" | "fish" | "deliver" | "stage" | "earn" | "guest" | "reserve" | "missed" | string;
  room_id: string | null; player_id: string | null; item_id: string | null; amount: number | null;
  data: {
    stage?: string; name?: string; index?: number; unlocks?: string[];
    // guest: how many stayed, the rate, the comfort that night; reserved/dog = the extra a special guest paid
    guests?: number; per_guest?: number; score?: number; skipped?: boolean; reserved?: number; dog?: number | boolean;
    due_day?: number; days?: number; // reserve
  } | null;
}
/** Signed pool changes since KST midnight (+ = the pool grew); `furniture` nets buys against refunds. */
export interface TodayTotals {
  earned: number; fish: number; fish_count: number; furniture: number; sold: number; deliver: number; guests: number;
}
export interface ActivityResponse {
  events: ActivityEvent[]; max: number; today: TodayTotals;
  progress: Record<string, RoomProgress>; locked: string[]; comfort: Record<string, ComfortView>;
}

export const api = {
  catalog: () => call<RawCatalog>("GET", "/api/catalog"),
  rooms: () => call<RoomsResponse>("GET", "/api/rooms"),
  activity: () => call<ActivityResponse>("GET", "/api/activity"),
  fishInfo: () => call<{ loot: { id: string; name: string; value: number }[]; cooldown_s: number }>("GET", "/api/fish"),
  fishStart: () => call<{ session: string; bites: { at_ms: number; window_ms: number; hold_ms: number }[] }>("POST", "/api/fish/start", {}),
  fishFinish: (session: string, holds: { start_ms: number; end_ms: number }[], escaped: boolean) =>
    call<FishFinishResponse>("POST", "/api/fish/finish", { session, holds, escaped }),
  fishDeliver: (seq: number, room?: string) =>
    call<{ balance: number; room: string; have: number; want: number; completed: { room: string; stage: string; name: string }[] }>("POST", "/api/fish/deliver", { seq, room }),
  register: (id: string) => call<{ id: string; token: string; existing: boolean; created: boolean; name: string; earned: number }>("POST", "/api/register", { id }),
  me: () => call<MeResponse>("GET", "/api/me"),
  sync: () => call<{ refreshed: boolean; balance: number; contributions: Contribution[] }>("POST", "/api/sync"),
  putAvatar: (a: AvatarLook) => call<{ avatar: AvatarLook }>("PUT", "/api/avatar", a),
  room: (roomId: string, etagVersion?: number) =>
    call<RoomResponse | null>("GET", `/api/room/${encodeURIComponent(roomId)}`, undefined,
      etagVersion === undefined || etagVersion < 0 ? {} : { "If-None-Match": `"${etagVersion}"` }),
  place: (room_id: string, item_id: string, x: number, y: number, span?: number | null) =>
    call<{ uid: number; balance: number; version: number; room: string }>("POST", "/api/room/place", { room_id, item_id, x, y, span: span ?? undefined }),
  move: (uid: number, x: number, y: number, span?: number | null) =>
    call<{ uid: number; version: number; balance: number }>("POST", "/api/room/move", { uid, x, y, span: span ?? undefined }),
  remove: (uid: number) => call<{ balance: number; version: number; room?: string; ruined?: number }>("DELETE", `/api/room/item/${uid}`),
  note: (uid: number, text: string) =>
    call<{ uid: number; version: number; room: string; note: string | null; note_by: string | null; note_ts: number | null }>("PUT", `/api/room/item/${uid}/note`, { text }),
  rotate: () => call<{ id: string; token: string }>("POST", "/api/token/rotate"),
  logins: () => call<{ logins: { ts: number; action: string; ip_hash: string; ua: string; ok: number }[] }>("GET", "/api/me/logins"),
  /** Verify a token without touching global state. */
  meWith: async (token: string): Promise<MeResponse> => {
    const res = await fetch("/api/me", { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new ApiError(res.status, "unauthorized");
    return (await res.json()) as MeResponse;
  },
};
