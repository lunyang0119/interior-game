/** Player-facing strings of the train minigame (해요체). Engine names (devices, hacks, orders) mirror strings.py. */

export const DEVICE_KO: Record<string, string> = { curtain: "커튼", coffeepot: "커피포트", light: "조명", speaker: "스피커" };
export const ORDER_KO: Record<string, string> = { move: "이동", search: "수색", scan: "추적", stay: "대기" };
export const HACK_KO: Record<string, string> = {
  ping: "핑", doorlock: "문 잠금", distract: "교란", blackout: "광학 재부팅", hide: "은신", overload: "과부하",
};

export const S = {
  loading: "불러오는 중…",
  needLogin: "먼저 방 게임에서 닉네임으로 들어와 주세요",
  previewNeedsAdmin: "미리보기는 관제만 볼 수 있어요. 비밀문구를 입력해 주세요",
  claimed: "이 계정이 관제가 됐어요",
  badSecret: "비밀문구가 틀렸어요",
  trainDisabled: "서버에 관제 비밀문구가 설정되지 않았어요",
  unknownMap: "없는 맵이에요",
  previewTitle: (id: string, n: number) => `${id} · ${n}칸`,
};

/** API error code → Korean toast. */
export const MESSAGES: Record<string, string> = {
  unauthorized: "로그인이 필요해요",
  rate_limited: "요청이 너무 잦아요. 잠시 후 다시 시도해 주세요",
  network: "네트워크 오류네요",
  not_admin: "관제만 할 수 있어요",
  bad_secret: S.badSecret,
  train_disabled: S.trainDisabled,
  unknown_map: S.unknownMap,
  no_game: "진행 중인 추적이 없어요",
  not_open: "지금은 명령을 제출할 수 없어요",
  paused: "잠시 멈춘 상태예요",
  not_hunter: "이 추적의 참가자가 아니에요",
  dazed: "증기에 휩싸여 이번 라운드는 행동할 수 없어요",
  unknown_room: "없는 구역이에요",
  not_adjacent: "지금 있는 곳에서 바로 갈 수 없는 구역이에요",
  is_admin: "관제는 승무원으로 탑승할 수 없어요",
  lobby_full: "정원이 가득 찼어요",
  game_active: "이미 진행 중인 추적이 있어요",
  not_enough_hunters: "승무원이 2명 이상 있어야 출발해요",
  vote_too_early: "아직 건너뛰기 투표를 열 수 없어요",
  vote_bad_target: "그 사람은 투표 대상이 아니에요",
  map_locked: "맵은 모집 중에만 바꿀 수 있어요",
  bad_config: "설정 값이 이상해요",
  ai_unavailable: "서버에 Gemini 키가 없어서 AI를 부를 수 없어요",
  fugitive_is_ai: "이 판의 도주자는 AI가 맡고 있어요",
};
