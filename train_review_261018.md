# 열차 추적(/train/) 코드 검토 — 2026-10-18

기준 커밋 2791c57 (branch 261018). 서버 로직은 e608147 이후 변경 없음. 8개 관점(서버 정책·엔진 규칙·시뮬레이션·클라이언트 흐름·UI/문구·AI 봇·문서/테스트·정보 노출)으로 읽고, 102개 후보를 76개로 병합한 뒤 각각 반박 시도 + 플레이어 체감 판정을 따로 돌렸다. 76개 중 반박된 것은 0개, 38개는 양쪽 모두 "확인", 나머지는 "일부 과장"으로 정정됨. 아래는 정정된 내용 기준. pytest 26개는 모두 통과.

## 0. 구조 요약

- **엔진** `server/app/train/engine.py` (디스코드 봇 레포 2182a11 그대로, 수정 금지). 정산 순서: 퀵핵 선효과 → 헌터 이동(잠긴 문은 범프) → 도주자 경로(잠긴 문 앞 정지) → 체포 판정 search > swap > colocate(contact 모드만) → 수색 결과/증기 마비 → 목격(glimpse) → 스캔(라운드 **시작** 시점 방의 장치, scan_lag 1) → 추적률 += passive(+스캔 5) → 100이면 traced(핵 봉인) → overheat_rounds 뒤 또는 max_rounds에 동결 → 보고(표식 지연 = 경계도, 교란 미끼 합산, 신호 밴드 = 가장 가까운 헌터 거리).
- **웹 정책** `game.py` Manager 하나가 asyncio.Lock 아래 모든 변경을 처리. 로비 → 라운드 타이머(저장된 deadline이 진실, 태스크는 깨우기용) → 조기 정산 + 도주자 유예 → 투표 → 일시정지/연장 → 스냅샷(`train_games`) → 역할별 브로드캐스트(`ws.py`, 매 메시지마다 role_of 재계산). AI는 라운드당 태스크 하나(`bot_task`/`fugitive_task`), Gemini 호출은 락 밖, 제출은 락 안.
- **설정 층** DEFAULTS → `scaling_web.json[좌석수]`(맵 포함) → `WEB_DEFAULTS`(1시간, early_resolve) → `data/train_config.json` → 관제 런타임 오버라이드. 문서(README 113, settings.py docstring)는 WEB_DEFAULTS와 scaling 순서를 반대로 적어 놨다(현재는 겹치는 키가 없어 무해).
- **웹 실효값** capture_mode=search, speed 1, 2~4명 car2077_9 / 5~6명 car2077_12, trace_passive 14/12/10/10/8, scan_budget 2/2/1/2/1, overheat 1/1/2/1/1, max_rounds 12, 유예 30분, 투표 개방 10분.
- **클라이언트** `main.ts`가 WebSocket 하나로 `tstate.payload`를 제자리 수정 → `applyState()` → 각 `ui/*.ts`가 `state:changed`로 재렌더. `round_resolved` → 재생 큐(`play()`/`playOne()`) → `TrainScene.play` → `Playback.playRound`(걷기, 버블, 목격, 체포 연출) → `playback:done` → localStorage `train_played` 기록. 재접속은 `maybeReplay()`가 안 본 라운드를 재생(처음 보는 게임은 최신 1개만).
- **역할 필터는 잘 지켜진다.** 헌터/관전자 페이로드에 도주자 방·RAM·경로가 들어가는 경로는 못 찾았다(테스트 FORBIDDEN_KEYS로도 보장). 아래 "노출"은 전부 설계상 공개되는 정보에서 추론되는 것들이다.

## 1. 고쳐야 할 버그 (플레이어가 직접 겪음)

| # | 내용 | 위치 | 고치는 방향 |
|---|---|---|---|
| F02 **high** | AI(봇 헌터나 AI 도주자)의 제출이 마지막이라 조기 정산을 일으키면 `_open_round → _schedule_ai`가 **지금 실행 중인 자기 태스크를 cancel** → 다음 await(`hub.send_each` round_resolved)에서 CancelledError → 아무도 round_resolved/round_open을 못 받음. 엔진·스냅샷·타이머는 다음 라운드로 넘어갔는데 화면은 이전 라운드에 멈춤. 새로고침해야 풀림. 체포 라운드는 영향 없음. | game.py `_schedule_bot_turn`, `_schedule_fugitive_turn` | `_cancel_timer`처럼 `t is not asyncio.current_task()` 가드 |
| F01 | `resultBubble()`이 `{search} 이상 없음` 같은 토큰 문자열을 돌려주는데 `fx.bubble()`은 Phaser 텍스트라 글자 그대로 찍힘. 거의 매 라운드 보임. (최신 UI 커밋에서 생김) | report.ts:66-71, Playback.ts:79-81 | 버블은 토큰 빼기 |
| F03 | 유예(grace) 중 헌터가 제출 취소해도 `grace_until`이 안 지워짐 → 전원 제출이 아닌데 유예 끝에 timed_out 정산, 취소자는 stay. HUD는 계속 "도주자 대기". 설계 문서는 취소 시 재평가한다고 적음. | game.py `cancel_hunter_order` | 취소 시 grace_until=None + deadline 푸시 |
| F08 | 유예 중 "+10분/+1시간"은 `deadline_ts`만 늘려서 `effective_deadline=min(deadline, grace)`가 그대로. 그런데 모두에게 "마감이 연장됐어요" 토스트가 나가고 HUD의 "도주자 대기" 라벨만 사라짐. 관제=도주자가 시간을 벌려고 누르는 바로 그 상황. | game.py `extend` | grace_until도 밀거나, 유예 중엔 버튼에 안내 |
| F21 | 도주자가 이동을 확정하면 바에 "제자리 · 바꾸기: 이동 → X"로 표시(ws `fugitive_submitted`에 내용이 없어 플레이스홀더를 넣음). 토스트와 모순. | main.ts:343, fugitive.ts confirmOrder | REST 응답의 `r.order`를 payload에 써 넣기 |
| F28 | 핑 뒤 서버가 아무것도 푸시 안 하고 클라도 응답의 ram/trace/pinged를 안 씀 → RAM·추적률 그대로, 핑 버튼 계속 활성(두 번째 누르면 400), 보고 패널은 "핑을 써야 보여요" 유지. | game.py `ping`, fugitive.ts `ping()` | 응답값 반영 + `pinged=true` |
| F23 | 은신 + 이동을 같이 제출하면 수락되고 "명령 접수: 이동 → X · 은신"이라고 뜨는데, 정산에서 이동이 조용히 버려짐(엔진 규칙). 4 RAM/+20 내고 제자리. | fugitive.ts, game.py | 은신 선택 시 move 비우고 안내 |
| F24 | 핵을 확정한 뒤 핑을 쓰면 RAM 1이 빠져서 정산 때 핵이 "RAM 부족 무효"로 조용히 사라짐(핑 비용은 그대로). 경고 없음. | game.py `ping` / fugitive.ts | 확정된 핵 비용 > ram-1이면 핑 거부 또는 경고 |
| F26 | 재생 시작·끝마다 아바타가 자기 방 안에서 다른 칸으로 순간이동(슬롯이 `report.order` 셔플 순서 vs `view.hunters` 순서). 4명이면 96% 라운드에서 보임. | Hunters.sync 호출(TrainScene.play, doSync) | 슬롯 순서를 하나로 고정 |
| F36 | 재생 끝나면 `tweens.pauseAll()`(절전)이 버블 fade 지연까지 멈춰서 결과 버블이 다음 라운드까지 화면에 남고, ◎·증기 펄스도 멈춤. | main.ts throttle | 버블은 scene.time으로, 또는 무한 펄스만 pause |
| F27 | 재생 중 `state`/`hello`가 오면(모바일 재접속, 관제 튠값 적용, 경로 공개 토글) 같은 라운드를 한 번 더 재생. 체포 배너도 두 번. | main.ts `maybeReplay` | `tstate.playing` 라운드는 제외 |
| F47 | 재생 중 HUD 칩이 다음 라운드 번호("R5 재생" while R4 plays), 시계도 이미 다음 라운드. | hud.ts | 재생 중엔 `tstate.playing.round` |
| F68 | 문 조우(swap) 체포 때 헌터 클라에선 실루엣이 체포 헌터의 방에 나타났다가 sync 뒤 실제 방으로 점프. | Playback.ts 5단계 | ws `captured.room` 또는 `view.capture_room` 사용 |
| F29 | "내 차례" 효과음·진동이 이전 라운드 **재생 시작** 때 울림(round_open이 round_resolved 직후 도착). 제출 바가 뜨는 순간엔 아무 신호 없음(탭 제목 뱃지만). | main.ts round_open 핸들러 | 재생 끝에 큐 |
| F37 | LOBBY/IDLE에서 모든 state push가 `openPanel('panel-lobby')`를 불러 열려 있던 도움말·관제·비밀문구 패널을 닫음(첫 방문 자동 도움말이 누가 탑승하면 사라짐). 튠값 폴드도 push마다 재렌더되어 입력 중인 값이 날아감. | lobby.ts render, admin.ts | 전환 시에만 열기 |
| F38 | 체포 뒤 비관제 플레이어는 탑승 버튼도 로비 패널도 없어 아무것도 못 함. 서버는 CAPTURED에서 누구나 `/game`을 열 수 있게 해 놨는데 버튼이 없음. 관제도 관제 패널 안의 2단계 "추적 종료"를 찾아야 함. | lobby.ts, hud.ts | CAPTURED에서도 로비/새 추적 노출 |
| F07 | `end_game`/`create`가 봇 태스크를 안 끊어서, 이전 게임 1라운드 Gemini 호출이 아직 돌면 새 게임 1라운드 봇이 영영 안 움직임(라운드 번호만 비교). 일시정지→재개로만 풀림. | game.py | 게임 식별까지 비교, end_game에서 cancel |
| F19 | 튠값 `signal_bands`에 "1,3" 형식이 아닌 값을 넣으면 정산 **커밋 뒤** 크래시 → engine RESOLVING, manager ROUND_OPEN, 모든 제출 400. 강제 정산으로 복구해도 position_history가 중복돼 표식이 한 라운드 더 밀림. | config.coerce, game.py `_resolve` | set_config에서 검증 |
| F20 | `round_timer_sec` ≤ 0이면 초당 약 88라운드 스핀(브로드캐스트+스냅샷). 양수로 되돌리면 멈춤. | game.py | 하한 검증 |
| F11 | 게임 중 헌터가 `/claim`하면 admin이 되면서 헌터 자리도 유지 → 도주자 뷰 + 헌터 슬롯(엔진이 그 슬롯 제출을 기다려 조기 정산 막힘), 원래 도주자는 말없이 관전자. 비밀키 필요. | game.py `claim` | 게임 중 거부 또는 슬롯 정리 |
| F66 | 타이머 태스크에 예외 가드가 없어 마감 정산 중 `_save` 실패(SQLite lock 등) 시 태스크가 죽고 다음 라운드는 자동 마감이 없음. 드묾. | game.py `_timer_loop` | try/except + 재무장 |
| F15 | 봇의 엔진 이름이 `bot:N`(제미나이-N은 버려짐) → 체포 배너·디스코드 웹훅 "수수께끼의 인영을 bot:1가 잡았다!", 핑 스트림 토스트 `bot:2: search`, 투표 토스트도 raw id. | game.py start_game `(h, h)`, main.ts:238/336/360 | new_game에 (uid, label) 넘기고 클라는 label() |
| F75 | `media/train/icons.*`가 VM에 없으면 잠금/증기 표식이 missing-texture 사각형, DOM 아이콘 전부 빈칸. `deploy.py TARGETS`에 `media/train/*.json`이 없음(ultrareview도 지적). | TrainBoot.ts, deploy.py | TARGETS 추가, README 배포 절차에 train-ui 명시 |

## 2. 플레이 체감상 부자연스러운 것 (설계·밸런스, 엔진은 수정 금지라 config/정책으로)

**핵심 둘**

- **F05 엔드게임이 추적률 동결로 결정됨.** 추적률은 단조 증가, passive 8~14라 핵 안 쓰고 스캔 없어도 R8~10에 100(핵 봉인), 1~2라운드 뒤 동결(실시간 표식, 이동 불가). 시뮬: 2~3명에선 체포의 90~100%가 **이미 동결된** 도주자를 잡는 것. "매 라운드 stay만 하다 동결 뒤 걸어가는" 헌터도 100% 승리(R13). 4·6명에선 60~68%가 동결 전 체포라 추격이 의미 있음. 엔진에 도주자 승리 조건이 없어서(max_rounds도 동결일 뿐) 도주자는 **이길 수 없고 늦출 수만** 있다. scaling_web 주석의 "p50 8~10라운드" 목표는 맞췄지만 그 수단이 안전장치다.
- **F04 유예 + 핑 = 도주자 완전정보 후수.** 전원 제출 → 유예 30분 → 도주자가 1 RAM(재생 1이라 사실상 공짜)으로 핑 → 모든 헌터 명령(이동 목적지 포함)을 보고 → 안 잡히는 수를 둠 → 즉시 정산. 헌터는 핑을 알 수 없고(ping_signature false; 도움말은 "역탐지 시그니처"가 뜬다고 하지만 기본 설정에선 절대 안 뜸), 추적률 +5 델타로만 추론 가능(F72). 시뮬: 매 라운드 핑은 동결을 2라운드 앞당겨 오히려 손해지만, 헌터가 인접할 때만 핑하면 4~6명의 동결 전 체포율이 절반으로 줌(61→19%, 41→4%, 73→41%). 화면상으론 헌터가 "승무원 전원 제출 — 침입자에게 유예"를 보고 기다리는데 수색한 방은 늘 비어 있는 경험.

**핵이 손해인 구조**

- F41 2~3명(passive 14/12, overheat 1)에선 핵 한 번의 추적률이 passive 0.7~1.4라운드치라, 핵을 쓸수록 동결이 빨라져 수명이 1~2라운드 줄어듦(p50 9 vs 10, 8 vs 10). 4명부턴 doorlock이 swap을 막아 중립~약간 이득.
- F06 **은신**은 search 모드에서 목격(glimpse)만 막음. 수색·문 조우는 그대로 잡히고, 그 라운드 이동 불가, 4 RAM/+20, 게다가 시그니처가 "커튼"(car2077_9에선 A1/B2 둘뿐)이라 "도주자가 커튼 방에 그대로 있음"을 알려줌. 봇 시뮬도 contact 모드에서만 hide를 씀. 사실상 함정 버튼.
- F35 scan_budget 2(2·3·5명)에서 두 번째 스캔은 같은 장치를 또 알려주고 +5만 더함 → 스캔은 탐지보다 "동결 타이머 누르기".
- F34 장치 핵은 전부 라운드 시작 방의 장치 클래스를 공개(과부하는 정확한 방). 의도된 트레이드오프지만 9칸 맵에선 2~3칸으로 좁혀진다. 시뮬상 승률엔 거의 영향 없고(진짜 비용은 추적률) 헌터용 설명이 없어 추론을 못 하는 게 더 문제.
- F25 교란 미끼가 실제 표식과 같은 방이면 하나로 합쳐지는데 문구는 "감지된 신호 중 하나는 가짜예요". 6명 R3(경계도 0)에선 어떤 ◎든 가짜.
- F14 자기 경로의 문을 잠그면 자기가 막혀서 제자리(2 RAM/+10 낭비, 문은 공개). "뒤의 문을 잠근다"는 자연스러운 의도가 바로 이 미스클릭. 바에 경고 없음.
- F59 신호 강도 '약'은 웹 맵(지름 4~5)에서 시뮬 26k 보고 중 0번. 사실상 "인접 여부" 2단계.

**시작·스케일**

- F12 시작 방이 항상 A2(편심 최소 + 알파벳 타이브레이크, "가장 중심"이 아니라 윗줄), 헌터 스폰도 고정(9칸: C1, C3, +B1, +B3). 두 번째 판부터 1~2라운드는 뻔함. 관제 오버라이드로 바꿀 순 있지만 문서 없음.
- F09 맵·밸런스가 **좌석 수**(create 때 고른 hunter_count) 기준. 6석 로비를 2명으로 출발하면 12칸 맵 + 6명 튜닝(regen 2, passive 8) → 시뮬상 2라운드 더 김. 로비에 경고 없음.
- F42 난이도가 단조롭지 않음: 4명(9칸, overheat 2)이 도주자에게 가장 길고, 5명(12칸)이 다시 쉬움. 원인은 맵보다 overheat_rounds와 5번째 스폰(A4, 시작 2칸 거리).
- F60 traced 단계(핵 봉인, 아직 이동 가능)가 1라운드(4명 2). 6명은 passive 8×12=96이라 핵·핑·스캔이 없으면 "추적률 100%" 문구 없이 R12 동결.

**AI 관련**

- F18 봇 헌터의 판단(명령 종류·목적지·이유)이 제출되자마자 `bot_reason`으로 **도주자에게 핑 없이** 감(README에 "도주자에게만"이라고 적은 의도된 설계). 봇이 섞이면 핑은 사람 상대로만 의미.
- F39 Gemini 호출에 타임아웃 없음(httpx timeout=None, wait_for 없음). 진짜 행이면 그 라운드 뒤 봇들은 아예 질문도 못 받고 1시간 마감까지. 1인+봇 2 이상이면 투표(need 2)로도 못 넘김. 일시적 503/429는 모델 3개×3회, 42초 백오프 뒤 대기로 떨어짐.
- F52 `bot_thinking`/`bot_reason`은 도주자 역할에만 가서, AI 도주자 판에서 관제가 헌터로 타면 **아무도** 못 받음. 헌터·관전자는 어떤 모드에서도 "(판단 중)" 표시를 못 봄(HUD·투표 패널엔 그 UI가 있는데).
- F22 투표 need가 봇·마비자 포함 전체 헌터 수 기준 → 2명+봇 2에서 AFK 한 명을 못 넘김(need 2, 투표자 1). 마비자는 투표 가능(원 주장 중 틀린 부분).
- F16 AI 도주자 프롬프트에 제출된 헌터 명령이 공짜로 들어감. 단 프롬프트는 라운드 열리자마자 만들어져서 보통은 비어 있고, 일시정지→재개·서버 재시작 때만 실제로 샘.
- F65 AI 도주자 프롬프트의 규칙 설명이 contact 모드/speed 2 기준(지나간 방 체포, 엇갈림만 체포, 은신=수색 외 안전). F51 파싱이 방 id를 대문자화해서 소문자 id 파일 맵에선 봇이 영영 못 움직임(현재 train_maps.json 없음).
- F57 일시정지 중 도착한 Gemini 답은 버려지고 재개 때 다시 물음(그 봇만). F64 체포 후 `ai_log`가 경로 공개 토글과 무관하게 AI 도주자의 라운드별 목적지·raw 예외 문자열까지 모두에게.

**권한·진행**

- F10 비밀키 없는 배포에선 **개설자만** 게임을 닫을 수 있음. 로비를 열고 사라지면 모두 "이미 진행 중인 추적이 있어요"로 막힘(DB 수정 외 방법 없음). 진행 중 게임은 헌터가 계속 제출하면 30분 유예마다 정산되고 동결 뒤 잡을 수 있어 덜 막힘.
- F56 반대로 CAPTURED 상태에선 누구나 API로 `/game`을 열어 관제를 가져갈 수 있음(버튼은 없음).
- F32 도주자=관제라 비공개 튠값(trace_passive, doorlock_range, ram…)을 라운드 중 몰래 바꿀 수 있고 범위 검증도 없음(trace_passive -50이면 영원히 추적 불가). `/round/end`로 헌터 명령 본 뒤 즉시 정산도 가능. 친구끼리라 신뢰 문제지만, 어떤 키가 덮였는지 이름만이라도 헌터에게 보이면 좋음.
- F17 `/api/register`로 도주자 닉네임을 다시 등록하면 토큰이 넘어와 도주자 뷰를 볼 수 있음(앱 전체의 닉네임 로그인 모델, 의도). 열차 모드는 처음 생긴 숨은 정보 모드라 여기서 처음 "치팅"이 됨. 피해자는 401로 알아챔.
- F40 투표로 stay가 된 헌터가 취소/덮어쓰기 가능(투표는 비워짐). 3명 이상에서만 실제로 진행을 막음. F67 2명 판에선 10분 뒤 한 명이 단독으로 상대를 넘김(수식상 불가피, 유예 30분 대비 10분이 짧은지는 정책).
- F45 유예 중 일시정지→재개하면 유예가 그대로 하드 마감이 됨(문서상 의도) + "도주자 대기" 라벨 사라짐.

## 3. 문구·도움말

- F30 사람 도주자에게 **퀵핵이 뭘 하는지** 설명이 어디에도 없음(버튼은 이름+비용, 도움말은 RAM/추적률/장치만). AI 프롬프트에만 제대로 된 [퀵핵 설명]이 있음. 과부하가 자기 방에 증기, 은신이 2라운드·이동 불가, 문 잠금 1라운드, 핑의 의미 모두 미설명.
- F31 도움말은 strings.py HELP/TUTORIAL 그대로라 합쇼체·해라체, 4개 행동이 세 번 반복, "접수 확인은 본인에게만 보입니다"는 웹에선 거짓(명령 내용이 전원 공개).
- F13 문 조우 체포는 **같은 방향으로 같은 문**을 지나도 성립하는데 모든 문구가 "엇갈려 지나면". 목격 뒤 같은 방에서 출발하는 흔한 상황에서 도주자가 뒤따라오는 헌터에게 잡히고 "규칙에 없던데?"가 됨. index.html 로비 블러브는 목격도 빠짐.
- F58 추적(스캔)이 "지금 있는 구역"이라고 하지만 실제는 라운드 시작 방(scan_lag 1).
- F62/F71 유예 문구가 도주자에게도 3인칭("도주자 대기", "침입자에게 유예"), 시계 툴팁/바 힌트는 "모두 확정하면 바로 정산"인데 도주자 미제출이면 30분 기다림. 도주자/침입자/관제 세 이름이 연결 설명 없이 섞임(관제(도주자)는 AI 도주자 모드에선 틀림).
- F43 "확정 = 이번 라운드의 내 RP 끝" — RP가 뭔지 설명 없음(디스코드 RP 용어). 같은 문장이 바로 뒤에 "다시 확정하면 덮어써요"라 자기모순.
- F48 ⏸ ▶ (관제 버튼), ⏱ (타임아웃 로그 줄)은 아직 이모지 코드포인트. ▒▮▯▓░●는 텍스트 글리프라 괜찮음.
- F49 시작 배너 "Activating Combat Mode"는 의도된 고정 문구. 한국어 GAME_START_INTRO는 안 쓰임.
- F70 토스트가 하나뿐이라 봇 이유 토스트는 15ms 뒤 다음 봇의 "판단 중"에 덮임, 퀵핵 감지 토스트도 traced/frozen 라운드엔 잘림.
- F61 중간 합류/새 기기/새로고침 시 판독 기록에 최신 1라운드만(페이로드엔 8개가 오는데 history에 안 넣음).
- F63 관전자에게 "내 위치" 버튼이 무반응. F53 "AI 승무원으로 채우기"가 항상 빈자리를 전부 채워 늦게 온 친구가 못 탐. F50 출발 3초 카운트다운은 관제 화면에만 있고, 카운트 중 state push가 오면 버튼이 재생성돼 라벨이 되돌아가고 탭하면 취소됨. F76 폰에서 HUD가 5~7줄로 접히는데 토스트는 1줄 기준 위치라 시계·추적률 칩을 덮음. F74 커버 줌이 소수(2.4x, 4.8x)라 픽셀아트가 미세하게 흔들림(공용 카메라의 의도된 선택).

## 4. 문서·테스트·기타

- F33 테스트 없음: 제출 취소(DELETE /order, /fugitive/order) 자체가 한 번도 안 불림, 게임 중 claim, 유예 중 extend, CAPTURED 복원 + 웹훅 재전송, 로비 map_id 변경, PAUSED에서 round/end, AI가 마지막 제출자인 경우(F02의 경로), 좌석 수 vs 탑승 수.
- F44/F55 docs/261013_train_plan.md 드리프트(test_train_ws.py 없음, /maps 공개, round_resolved {report, state}, 취소 재평가 없음, error 메시지 없음, 설정 층 순서) + settings.py docstring/README 113의 층 순서 오기 + ws.py docstring에 fugitive_submitted/bot_* 누락 + test_train.py:418 주석 거짓 + `_require_game` 중복 호출.
- F54 배포: 기존 VM엔 `pip install -e .`(google-genai) 안내 없음, `.env.example`에 TRAIN_*·GEMINI_API_KEY 없음, deploy.py TARGETS에 `data/train_interiors.json`(재시작 필요)·`train_maps.json`·`media/train/*.json` 없음.
- F46 로비에서 state push마다 연결별로 scaling/train_config 파일을 다시 읽음(μs 단위, 무해). F69 10fps 절전은 탭을 한 번 숨겼다 켜기 전엔 작동 안 함(Phaser 3.90이 start/wake에서만 step 바인딩). F73 join/leave에 전용 레이트리밋 없고 no-op에도 스냅샷+전체 푸시.

## 5. 시뮬레이션 참고 수치

`python -m app.train.sim --all --games 400 --seed 1 --scaling app\train\scaling_web.json` (N style p50 / frz%=체포 시 이미 동결 / how):
2 hacker 9 / 100% / search 400 · 2 stealth 10 / 90% · 3 hacker 8 / 99% · 3 stealth 10 / 90% · 4 hacker 10 / 74% · 4 stealth 7 / 38% (swap 158) · 5 hacker 8 / 91% · 5 stealth 10 / 55% · 6 hacker 10 / 70% · 6 stealth 9 / 31% (swap 234). colocate 0(search 모드).
스크립트: scratchpad `simulation\analysis*.py`, `rules-balance\probe.py`, `verify-F*\`.
