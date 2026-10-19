/** Player-facing strings of the train minigame (해요체). Engine names (devices, hacks, orders) mirror strings.py. */

export const DEVICE_KO: Record<string, string> = { curtain: "커튼", coffeepot: "커피포트", light: "조명", speaker: "스피커" };
export const ORDER_KO: Record<string, string> = { move: "이동", search: "수색", scan: "추적", stay: "대기" };
export const HACK_KO: Record<string, string> = {
  ping: "핑", doorlock: "문 잠금", distract: "교란", blackout: "광학 재부팅", hide: "은신", overload: "과부하",
};

export const S = {
  loading: "불러오는 중…",
  needLogin: "닉네임으로 들어와 주세요",
  loginLost: (id: string) => `${id} 로그인이 풀렸어요 (다른 기기에서 들어왔을 수 있어요). 닉네임을 다시 입력해서 들어와주세요.`,
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
  grace_active: "유예 중에는 마감을 늘릴 수 없어요",
  game_running: "추적이 진행 중일 땐 관제를 바꿀 수 없어요",
  ping_breaks_hack: "핑을 쓰면 확정한 퀵핵의 RAM이 모자라요. 퀵핵을 먼저 바꿔 주세요",
  hide_no_move: "은신 중엔 이동할 수 없어요",
  voted_stay: "투표로 대기 처리된 라운드예요",
};

/** What each quickhack does, for the fugitive's buttons and the help panel (the engine rules under capture_mode=search). */
export const HACK_DESC: Record<string, string> = {
  ping: "지금까지 제출된 승무원 명령을 이동 목적지까지 바로 보여줘요. 승무원 보고에는 역탐지 시그니처가 남아요",
  doorlock: "고른 문 하나를 이번 라운드 동안 잠가요. 승무원도 나도 못 지나가고, 잠긴 문은 정산 때 모두에게 공개돼요",
  distract: "고른 구역에 가짜 ◎ 표식을 띄워요. 진짜 표식과 같은 구역이면 하나로 합쳐져요",
  blackout: "이번 라운드 승무원 보고를 잡음으로 덮어요. 표식·신호 강도·추적 결과가 모두 판독 불가가 돼요",
  hide: "이번 라운드는 이동하지 않고 숨어요. 같은 구역에 온 승무원에게 목격되지 않지만, 수색과 문 조우에는 그대로 잡혀요",
  overload: "지금 구역에 증기를 채워요. 여기서 라운드를 마친 승무원은 다음 라운드 행동 불가, 여기 수색도 실패해요. 증기는 모두에게 보여요",
};
