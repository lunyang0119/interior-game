/** Player-facing strings of the train minigame (해요체). Engine names (devices, hacks, orders) mirror strings.py.
 *  Words: the hidden player is the 침입자 (engine "fugitive"), the seekers are 승무원, the account holding the
 *  controls is the 방장 (engine "admin"); the whole game is a 추적, the scan action is 신호 탐색. */

export const DEVICE_KO: Record<string, string> = { curtain: "커튼", coffeepot: "커피포트", light: "조명", speaker: "스피커" };
export const ORDER_KO: Record<string, string> = { move: "이동", search: "수색", scan: "신호 탐색", stay: "대기" };
/** one line under each action button: what the action does, so the bar explains itself */
export const ORDER_DESC: Record<string, string> = {
  move: "옆 구역을 눌러요",
  search: "지금 구역을 뒤져요 · 침입자가 있으면 체포",
  scan: "침입자가 있는 구역의 장치 종류를 알아내요",
  stay: "제자리에 있어요",
};
export const HACK_KO: Record<string, string> = {
  ping: "핑", doorlock: "문 잠금", distract: "교란", blackout: "광학 재부팅", hide: "은신", overload: "과부하",
};

export const S = {
  loading: "불러오는 중…",
  needLogin: "닉네임으로 들어와 주세요",
  loginLost: (id: string) => `${id} 로그인이 풀렸어요 (다른 기기에서 들어왔을 수 있어요). 닉네임을 다시 입력해서 들어와주세요.`,
  previewNeedsAdmin: "미리보기는 방장만 볼 수 있어요. 비밀문구를 입력해 주세요",
  claimed: "이 계정이 방장이 됐어요",
  badSecret: "비밀문구가 틀렸어요",
  trainDisabled: "서버에 방장 비밀문구가 설정되지 않았어요",
  unknownMap: "없는 맵이에요",
  previewTitle: (id: string, n: number) => `${id} · ${n}칸`,
};

/** API error code → Korean toast. */
export const MESSAGES: Record<string, string> = {
  unauthorized: "로그인이 필요해요",
  rate_limited: "요청이 너무 잦아요. 잠시 후 다시 시도해 주세요",
  network: "네트워크 오류네요",
  not_admin: "방장만 할 수 있어요",
  bad_secret: S.badSecret,
  train_disabled: S.trainDisabled,
  unknown_map: S.unknownMap,
  no_game: "진행 중인 추적이 없어요",
  not_open: "지금은 행동을 제출할 수 없어요",
  paused: "잠시 멈춘 상태예요",
  not_hunter: "이 추적의 참가자가 아니에요",
  dazed: "증기에 휩싸여 이번 라운드는 행동할 수 없어요",
  unknown_room: "없는 구역이에요",
  not_adjacent: "지금 있는 곳에서 바로 갈 수 없는 구역이에요",
  is_admin: "침입자 역할은 승무원으로 탑승할 수 없어요",
  lobby_full: "정원이 가득 찼어요",
  game_active: "이미 진행 중인 추적이 있어요",
  not_enough_hunters: "승무원이 2명 이상 있어야 출발해요",
  vote_too_early: "아직 건너뛰기 투표를 열 수 없어요",
  vote_bad_target: "그 사람은 투표 대상이 아니에요",
  map_locked: "맵은 모집 중에만 바꿀 수 있어요",
  bad_config: "설정 값이 이상해요",
  ai_unavailable: "서버에 Gemini 키가 없어서 AI를 부를 수 없어요",
  fugitive_is_ai: "이 판의 침입자는 AI가 맡고 있어요",
  grace_active: "유예 중에는 마감을 늘릴 수 없어요",
  game_running: "추적이 진행 중일 땐 방장을 바꿀 수 없어요",
  ping_breaks_hack: "핑을 쓰면 확정한 퀵핵의 RAM이 모자라요. 퀵핵을 먼저 바꿔 주세요",
  hide_no_move: "은신 중엔 이동할 수 없어요",
  voted_stay: "투표로 대기 처리된 라운드예요",
};

/** What each quickhack does, for the intruder's buttons and the help panel (the engine rules under capture_mode=search). */
export const HACK_DESC: Record<string, string> = {
  ping: "지금까지 제출된 승무원 행동을 이동 목적지까지 바로 보여줘요. 승무원 보고에는 역탐지 흔적이 남아요",
  doorlock: "고른 문 하나를 이번 라운드 동안 잠가요. 승무원도 나도 못 지나가고, 잠긴 문은 라운드 결과에서 모두에게 공개돼요",
  distract: "고른 구역에 가짜 ◎ 표식을 띄워요. 진짜 표식과 같은 구역이면 하나로 합쳐져요",
  blackout: "이번 라운드 승무원 보고를 잡음으로 덮어요. 표식·신호 강도·신호 탐색 결과가 모두 판독 불가가 돼요",
  hide: "이번 라운드는 이동하지 않고 숨어요. 같은 구역에 온 승무원에게 목격되지 않지만, 수색과 문 조우에는 그대로 잡혀요",
  overload: "지금 구역에 증기를 채워요. 여기서 라운드를 마친 승무원은 다음 라운드 행동 불가, 여기 수색도 실패해요. 증기는 모두에게 보여요",
};
