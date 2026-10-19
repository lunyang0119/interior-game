# 열차 추적 미니게임 (/train/) — Phase 0 설계

2026-10-13. Discord 봇 레포 commit 2182a11 의 `engine.py / config.py 
/ strings.py / sim.py / scaling_web.json` 을 규칙의 단일 원본으로 두고, 이 레포에 격리된 라우트 `/train/` 로 올린다.
엔진은 수정하지 않는다. 서버 정책(타이머·투표·일시정지·권한)과 클라이언트 렌더링만 새로 쓴다.

## 1. 파일 계획

### 서버 `server/app/train/`
| 파일 | 내용 |
|---|---|
| `__init__.py` | 빈 파일 |
| `engine.py` `config.py` `strings.py` `sim.py` | 원본 그대로 복사. 첫 줄에 `# Copied unchanged from <discord bot repo> commit 2182a11` 주석만 추가. `config.load_sheet_data` 는 호출하지 않는다(gspread 는 지연 import 라 설치 불필요). `cd server && python -m app.train.sim --all --scaling app/train/scaling_web.json` 으로 시뮬 실행 |
| `scaling_web.json` | 원본 그대로 복사 (pyproject `package-data` 에 등록) |
| `utils.py` | 원본 `utils.py` 에서 `get_korean_particle`, `ends_with_hangul` 두 함수만 (같은 헤더 주석) |
| `settings.py` | 설정 합성: `DEFAULTS` → `scaling_web.json[좌석 수]`(`map_id` 포함) → `WEB_DEFAULTS`(`round_timer_sec 3600`, `early_resolve` 등) → `data/train_config.json`(선택; 평평한 키 다음에 좌석 수별 섹션 `"2"`..`"6"`) → 관리자 런타임 오버라이드. 맵·밸런스는 좌석 수가 아니라 실제로 탑승한 인원 수로 고른다. 전부 `config.coerce` 로 타입 강제. `vote_skip_after_sec`, `fugitive_grace_sec`, `round_timer_sec`, `early_resolve` 는 서버 정책 키 |
| `views.py` | 역할별 투영(순수 함수): `hunter_payload(game)`, `fugitive_payload(game)`, `public_report(report)`. 테스트가 직접 호출 |
| `store.py` | SQLite 스냅샷/복원: `save(conn, game)`, `load_active(conn)`, `train_meta` (admin_id) |
| `game.py` | `TrainGame`(엔진 상태 + 정책 상태) 과 `Manager`(이벤트 루프 소유 단일 인스턴스): 생성/로비/시작/제출/핑/투표/정산/일시정지/타이머 태스크/재시작 복원/웹훅. 모든 변경은 `async with self.lock` 안에서 → `store.save` → 브로드캐스트 |
| `router.py` | `/api/train/*` (아래 §2). 핸들러는 `async def` 로 루프에서 바로 `Manager` 호출. DB 는 `asyncio.to_thread` |
| `ws.py` | `/ws/train`. 자체 `TrainHub`(pid → ws 집합, 역할 캐시). `presence.hub` 와 무관 |

기존 파일 수정: `server/app/config.py`(+`TRAIN_ADMIN_SECRET`, `TRAIN_WEBHOOK_URL`, `TRAIN_CONFIG_PATH`), `server/app/main.py`(라우터 2개 include, lifespan 에서 `manager.start()/stop()`), `server/pyproject.toml`(`app.train` 패키지, json package-data), `server/migrations/016_train.sql`, `README.md`(env 2개, /train/ 설명), `tools/preprocess/deploy.py TARGETS`(`data/train_config.json`, `server/app/train/*.json`, `server/static/train/index.html`), `deploy/sync.sh` 는 server/app 전체를 보내므로 변경 없음.

테스트 `server/tests/test_train.py`(ws 테스트도 같은 파일): §5.

### 클라이언트
`client/train/index.html` + `client/src/train/` (Vite multipage: `vite.config.ts` 의 `rolldownOptions.input = { main: "index.html", train: "train/index.html" }` → `server/static/train/index.html`, FastAPI `StaticFiles(html=True)` 가 `/train/` 을 그대로 서빙. Caddy 변경 없음).

| 파일 | 내용 |
|---|---|
| `train/index.html` | 캔버스 + DOM 오버레이(HUD, 제출 패널, 투표, 보고, 로비, 관리자 패널, 토스트) |
| `src/train/main.ts` | 부팅: `storage.ts` 의 공용 계정/토큰(없으면 계정 패널 `ui/account.ts`: 닉네임 로그인·전환·복구 링크, 방 게임과 같은 `/api/register`) → `?preview=<map_id>` 면 미리보기 모드 → Phaser.Game + WS |
| `src/train/bus.ts` `state.ts` `strings.ts` | 자체 이벤트 버스, 상태, 한국어 문자열(해요체) |
| `src/train/api.ts` | `call()` 복사(엔드포인트 /api/train/*, 에러 코드 → 한국어) |
| `src/train/ws.ts` | `GameSocket` 복사 + 엔드포인트 인자(`/ws/train`) |
| `src/train/scenes/TrainBoot.ts` | 인테리어 아틀라스 + 캐릭터 로드 (`assets.ts`, `AvatarLoader.ts` 재사용) |
| `src/train/scenes/TrainScene.ts` | 장면: 맵 빌드, 아바타, 재생, 입력(`input/Gestures.ts`, `CameraController`) |
| `src/train/render/CarMap.ts` | 데이터 주도 레이아웃: 엔진 `rooms[{id,col,row,device,neighbors}]` → 객실 블록(바닥 6×4 + 벽 1줄), 이웃 방향의 벽에 문 틈, 방마다 장치 스프라이트 1개, 방 라벨. 걷기 그리드(`room/walk.ts` BFS 재사용) |
| `src/train/render/Hunters.ts` | 헌터 `Avatar`(색 태그), `walkPath` 재생, 잠긴 문 범프 |
| `src/train/render/Fugitive.ts` | 도주자 실루엣: LimeZu 아바타 + 검은 틴트 + 글리치(WebGL 이면 postFX 파이프라인, Canvas 면 알파 깜빡임). 추적 티어 0→3 강도, 동결 시 고정+최대("과부하") |
| `src/train/render/Fx.ts` | 정전(어둠 오버레이 알파 플리커), 교란(스피커 마커), 은신(커튼), 과부하(커피포트 증기), 신호 감지·마지막 목격 마커, 수색 결과 말풍선 |
| `src/train/render/Playback.ts` | 라운드 재생 시퀀서: 선효과 → 헌터 이동 → 결과 → 다음 SUBMIT |
| `src/train/ui/*.ts` | `hud`(라운드/마감 카운트다운/추적률), `lobby`, `submit`(방·장치 선택, "이번 라운드 행동 확정"), `vote`, `report`, `admin`(튠 패널 set/get, 일시정지/연장/라운드 종료/게임 종료, 미리보기), `claim`(비밀키 입력) |
| `src/train/style.css` | 공용 `style.css` 를 import 하고 추가 클래스만 |

에셋: `tools/preprocess/slices.json` 에 `train_floor`, `train_wall`, `train_wall_door`, `train_window`, `train_dev_curtain`, `train_dev_coffeepot`, `train_dev_light`, `train_dev_speaker`, `train_seat` 슬라이스 추가(LimeZu Generic/Kitchen 팩에서 선택) → `preprocess.py build` 로 인테리어 아틀라스에 포함. 서버 매니페스트에는 `train_` 접두 키가 들어가지만 `items.json` 에는 넣지 않는다(상점 미노출).

## 2. API / WS 스키마

### REST `/api/train` (모두 Bearer, `auth.current_player`; 실패는 `{"error": code}`)
| 메서드 경로 | 역할 | 본문 → 응답 |
|---|---|---|
| `GET /state` | 누구나 | 역할별 페이로드(§4). 게임 없으면 `{"status":"IDLE","role":...}` |
| `POST /claim` | 누구나 | `{secret}` → `{"role":"fugitive"}`. `TRAIN_ADMIN_SECRET` 과 `secrets.compare_digest`; 비어 있으면 403 `train_disabled`. 호출자 pid 를 `train_meta.admin_id` 에 저장(이전 바인딩 교체). 실패 5회/분 IP 제한, `log_access("train_claim")` |
| `POST /game` | admin | `{hunter_count: 2..6, map_id?: str, overrides?: {key: value}}` → 로비 생성(IDLE/ENDED/CAPTURED 에서만, 아니면 409 `game_active`) |
| `POST /join` `POST /leave` | 헌터 | 로비에서만. admin 은 join 불가(`is_admin`). 정원 = hunter_count |
| `POST /start` | admin | 로비 인원 ≥ 2 → `engine.new_game` → ROUND_OPEN |
| `POST /order` | 헌터 | `{type: move\|search\|scan\|stay, target?: room}` → `{order}`. 엔진 `RuleError` 코드 → 400 `not_open/not_hunter/dazed/unknown_room/not_adjacent` |
| `POST /fugitive/order` | fugitive | `{move?: room, hack?: doorlock\|distract\|blackout\|hide\|overload, target?: edge\|room}` → `{order}` |
| `POST /fugitive/ping` | fugitive | `{}` → `{orders: {id: {type,target}\|null}, ram, trace}` |
| `DELETE /fugitive/order` `DELETE /order` | 각자 | 제출 취소(ROUND_OPEN 중, 정산 전까지). 취소 시 조기 정산 조건과 유예를 다시 평가(유예 중 취소하면 유예 해제)하고 투표 대상이 다시 가능해짐 |
| `POST /vote` | 헌터 | `{target: hunter_id}` → `{votes, need, passed}` (§3 규칙) |
| `GET /config` `PUT /config` | admin | `{config, overrides, map_id}` / `{set: {key: value}}` → coerce 후 현재 게임 `st.config` 에 즉시 반영, `map_id` 는 LOBBY 에서만 |
| `POST /pause` `POST /resume` | admin | |
| `POST /extend` | admin | `{sec: 1..604800}` → 마감 연장(PAUSED 면 `paused_remaining` 에 더함) |
| `POST /round/end` | admin | 지금 정산(`timed_out=True` 의미: 미제출자 대기) |
| `POST /game/end` | admin | 상태 ENDED, 게임 해제 |
| `GET /maps` `GET /maps/{id}` | 공개 | `[{id, rooms: n, cols, rows}]` / `{id, rooms: [{id,col,row,device,neighbors}]}` (미리보기용) |

### WS `/ws/train`
첫 메시지 `{"type":"auth","token"}`(5초, 실패 4401). 이후 서버→클라이언트만, 예외는 `ping/pong`. 클라이언트의 `move` 류 메시지는 전부 무시(위치는 정산으로만 바뀜). 모든 수신 메시지는 pydantic 모델로 검증, 불일치는 drop.

| 타입 | 대상 | 내용 |
|---|---|---|
| `hello` | 본인 | `{role, state: 역할별 페이로드}` |
| `state` | 역할별 | 전체 페이로드 재전송(로비 변경, 재접속, config 변경, 제출 취소 등 "작은 변화" 전부 이걸로 통일) |
| `round_open` | 모두 | `{round, deadline_ts, vote_after_ts}` |
| `submitted` | 모두 | `{id, submitted: true\|false}` (내용 없음) |
| `hunter_order` | fugitive | 핑 이후 같은 라운드의 헌터 제출 `{id, order}` |
| `deadline` | 모두 | `{deadline_ts, reason: grace\|extend}` |
| `vote` | 모두 | `{target, voters: [id], need, passed}` |
| `round_resolved` | 역할별 | 헌터·관전자: `{report: public_report, state}` / fugitive: `{report: 전체(fugitive_path 포함), state, log_entry}` |
| `escaped` | 모두 | `{round}` 신호 동결 전에 못 잡아 도주자 탈출(`ESCAPED`, 정책 `escape_on_freeze`) |
| `captured` | 모두 | `{by, how, room, line: CAPTURE_LINE 포맷 결과}` |
| `paused` `resumed` | 모두 | `{paused_remaining}` / `{deadline_ts}` |
| `ended` | 모두 | `{}` |

### 마이그레이션 `016_train.sql`
```sql
-- 열차 추적 미니게임 (server/app/train). 한 번에 한 판; 상태 전환마다 엔진 상태 + 서버 정책을 통째로 스냅샷.
CREATE TABLE train_games (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  status     TEXT NOT NULL,          -- LOBBY | ROUND_OPEN | PAUSED | CAPTURED | ESCAPED | ENDED
  state_json TEXT NOT NULL,          -- {"engine": GameState.to_dict() | null(로비), "policy": {...}}
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX idx_train_games_status ON train_games(status);
-- 관리자(=도주자) 바인딩은 게임보다 오래 산다: /api/train/claim 이 player id 를 적는다
CREATE TABLE train_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
```
`policy` JSON: `{map_id, hunter_count, overrides, lobby: [pid], round_open_ts, deadline_ts, grace_until, paused_remaining, votes: {target: [voter]}, webhook_sent, pause_shift}`. 활성 게임 = `status != 'ENDED'` 인 최신 행 하나.

## 3. 상태 머신 (서버 정책, 엔진 status 위에 얹음)

```
IDLE ──admin POST /game──▶ LOBBY ──admin /start (n≥2)──▶ ROUND_OPEN ──정산──▶ ROUND_OPEN (다음 라운드)
                              │                              │  ▲                 │
                              └─/game/end──▶ ENDED           │  └─/resume──PAUSED │
                                                             │        ▲           │
                                                             └─/pause─┘           └─체포──▶ CAPTURED ──/game/end 또는 새 /game──▶ ENDED
                                                                                       (동결 전 미체포: ESCAPED, 이후 동일)
```
- **ROUND_OPEN 진입**: `round_open_ts = now`, `deadline_ts = now + round_timer_sec`, `grace_until = None`, `votes = {}`. 타이머 태스크 재무장(아래). `round_open` 브로드캐스트.
- **제출**: 헌터 → `engine.submit_hunter_order`; 도주자 → `engine.submit_fugitive_order`; 핑 → `engine.cast_ping`. 제출/취소 후마다 **조기 정산 평가**: `early_resolve` 이고 `st.all_hunters_submitted()` 이면 → 도주자 `order` 가 있거나 `frozen` 이면 즉시 정산, 아니면 `grace_until = min(deadline_ts, now + fugitive_grace_sec)` 를 한 번 세우고 `deadline` 브로드캐스트. 그 뒤 도주자가 제출하면 즉시 정산.
- **타이머**: 단일 태스크가 `min(deadline_ts, grace_until) - now` 를 60초 단위로 끊어 자며 매번 저장된 마감을 다시 읽는다. 0 이하 → `resolve(timed_out=True)`. 마감이 바뀌는 모든 전환(연장·유예·재개·복원)은 태스크를 취소하고 다시 만든다. 재시작 시 DB 의 `deadline_ts` 가 진실: 이미 지났으면 부팅 직후 정산.
- **정산** (`RESOLVING`, 락 안에서 원자적): `report = engine.resolve_round(st, timed_out=...)`(시드는 엔진이 `log[-1]["seed"]` 에 기록) → 스냅샷 → `round_resolved` 역할별 → `CAPTURED` 면 `captured` 브로드캐스트 + 웹훅(`CAPTURE_LINE.format(name, particle=get_korean_particle(name,"이","가"))` 만 1회, `webhook_sent` 로 재시작 후에도 중복 금지, 실패는 로그만) / 아니면 다음 ROUND_OPEN.
- **PAUSED**: `st.status = PAUSED`, `paused_remaining = deadline - now`(유예 중이면 유예 기준), 타이머 취소. **resume**: `deadline_ts = now + paused_remaining`, `round_open_ts += 멈춘 시간`(투표 개방 시점도 함께 밀림), 타이머 재무장. 복원 시 PAUSED 는 타이머 없이 복원. PAUSED 중 제출/투표는 409 `paused`.
- **extend**: ROUND_OPEN 이면 `deadline_ts += sec`(유예가 걸려 있으면 유예는 유지), PAUSED 면 `paused_remaining += sec`.
- **round/end**: 즉시 `resolve(timed_out=True)`. **game/end**: ENDED 저장, `ended` 브로드캐스트, 메모리 해제.
- **투표**: `POST /vote {target}` 허용 조건 ① ROUND_OPEN ② `now ≥ round_open_ts + vote_skip_after_sec` (403 `vote_too_early`) ③ 투표자는 헌터이며 `target ≠ 자신` ④ target 은 미제출·비마비 헌터(400 `vote_bad_target`) ⑤ 도주자는 대상 불가(헌터 목록에 없으니 ④로 걸림). `votes[target]` 에 투표자 추가(중복 무시). 통과 기준 `need = (n-1)//2 + 1` (n=헌터 수; 2명→1표, 3명→2표, 4명→2표). 통과 시 서버가 `submit_hunter_order(target, "stay")` 를 대신 제출하고 조기 정산 평가. target 이 먼저 제출하면 `votes[target]` 삭제(무효). 매 라운드 초기화. 모든 변화에 `vote` 브로드캐스트.
- **권한**: 역할은 요청마다 서버가 다시 계산 — `fugitive` ⇔ `pid == train_meta.admin_id`, `hunter` ⇔ `pid in st.hunters`, 그 외 `spectator`(헌터용 공개 뷰만, 제출 불가). 관리자 id 목록은 어떤 응답에도 넣지 않는다(`/api/register` 가 닉네임으로 토큰을 재발급하므로 비밀키가 게이트).

## 4. 역할별 직렬화 필드

**헌터 / 관전자 (`hunter_payload`)** — 엔진 `public_view()` 와 `public_report()` 만 사용:
```
status, round_no, deadline_ts, grace_until, paused_remaining, vote_after_ts, role,
you: {id, room, order: {type, target} | null, dazed}            # 본인 것만
view: PublicView 그대로 — round_no, status, trace, bar, signal, hunters[{name, room, tag, submitted, dazed, color}],
      locks, markers, steam, map_rows, map_id, capture_room(CAPTURED 뒤에만), playback(=playback.hunters), glimpses
report: 마지막 report 에서 playback.fugitive_path 를 제거한 사본 — round, trace, bar, tier, signal, distance, signature,
      markers, locks, steam, blackout, events[{type, uid, room?, edge?, device?}], order, timed_out, traced, frozen,
      captured_by, capture_how, hunters{uid: {name, room}}, playback.hunters
votes: {target: [voter]}, need
config: {round_timer_sec, fugitive_grace_sec, early_resolve, vote_skip_after_sec, scan_budget, max_rounds,
         fugitive_speed, capture_mode, signal_mode, hunter_colors}   # 공개 튠값만
lobby: [pid], hunter_count, map_id (LOBBY 중)
```
절대 포함 금지(테스트로 보장): `fugitive`, `fugitive_path`, `position_history`, `log`, `hidden_events`, `seed`, `ram`, `hidden_until`, `hacks_*`, `traced_at`, 어떤 형태의 도주자 방(`capture_room` 은 CAPTURED 뒤 예외), `admin_id`, `sheet`.

**도주자 = 관리자 (`fugitive_payload`)** — 위 전부 +
```
fugitive: {room, ram, trace, tier, hidden_until, frozen, hacks_disabled, traced_at, ping_round, order}
hacks: {hack: {ok, why, cost, trace}}                          # engine.hack_available 결과
reachable: [room]  (distance ≤ fugitive_speed), lockable_edges: [edge], decoy_targets: [room]
hunters_full: {id: {name, room, submitted, dazed_until, order: {type,target} | null(핑 전엔 null)}}
report: fugitive_path 포함 전체, log: 전체 엔트리(seed, fugitive_path, hidden_events …), position_history
config: 전체 st.config, overrides, map_id, policy: {deadline_ts, grace_until, paused_remaining, votes, webhook_sent}
```
헌터 명령 **내용**은 핑 전에는 `null`, `cast_ping` 응답과 그 뒤 같은 라운드의 `hunter_order` 스트림으로만 전달(엔진의 핑 의미 유지). 제출 **여부**는 공개 뷰대로 항상 보임.

## 5. 테스트 (`server/tests/test_train.py`)
- 역할 필터: 헌터 WS `hello/state/round_resolved` 와 `GET /state` 를 JSON 직렬화한 문자열에 `fugitive_path`, `"fugitive"`, `position_history`, `hidden_events`, `seed`, `ram`, 도주자 방 id(시작 방) 가 없다. 도주자 페이로드에는 있다.
- `sheet` 문자열이 `/api/train/*` 응답과 WS 프레임에 없다(기존 패턴).
- 투표: 개방 전 403, 자기 자신/제출자/도주자 대상 400, 2명→1표 통과 후 대상 명령이 `stay`, 대상이 먼저 제출하면 무효, 라운드 넘어가면 초기화.
- 타이머 복원: 마감이 지난 ROUND_OPEN 행을 넣고 앱을 다시 띄우면 부팅 중 `timed_out=True` 로 정산되어 `round_no` 가 1 올라간다; 마감이 남은 행은 상태 유지 + `deadline_ts` 그대로.
- 일시정지/재개: `paused_remaining` 보존, PAUSED 복원 시 타이머 없음, PAUSED 중 제출 409, 재개 후 `deadline_ts ≈ now + remaining`.
- 조기 정산/유예: 전원 제출 + 도주자 미제출 → `grace_until` 세팅; 도주자 제출 → 즉시 정산.
- claim: 틀린 비밀키 403, 맞으면 role fugitive, 다른 계정이 다시 claim 하면 교체.
- 엔진 복사 무결성: `hashlib.sha256` 으로 `reference/*.py` 와 `server/app/train/*.py`(헤더 1줄 제거 후) 가 동일.

## 5b. Phase 0 리뷰 후 조정 (2026-10-13)
1. `COMBAT_MODE_ON` 은 **게임 시작** 문장: 라운드 1이 열릴 때 사이트(ws `started`)와 디스코드 웹훅에 한 줄. 체포 연출은 틴트 해제 → `CAPTURE_LINE` 만.
2. 헌터 명령 **내용은 헌터·관전자에게 공개**(목적지 포함, 제출마다 갱신): ws `submitted` 가 `order` 를 싣는다. 도주자는 핑 전엔 제출 여부만 — `hunters_full[*].order` 와 `orders` 는 `fugitive.ping_round == round_no` 일 때만 채워지고, 핑 뒤 제출은 `hunter_order` 스트림으로 간다.
3. 재접속 재생: 클라이언트가 마지막으로 끝까지 재생한 라운드를 localStorage(try/catch)에 두고, `hello`/`state` 의 `report.round` 가 더 크면 그 라운드 playback 을 한 번 재생한 뒤 SUBMIT 으로 간다.
4. 헌터 이름 = player id, 비참가 로그인 사용자 = 관전자.

## 6. 작업 단계
- Phase 1 서버: 엔진 복사·settings·store·game·router·ws·migration·config/main·tests.
- Phase 2 클라이언트 뼈대: Vite multipage, 부팅, WS, 로비/제출/투표/보고 DOM, 데이터 주도 `CarMap`(임시 타일: 기존 `tile_*`), 헌터 재생.
- Phase 3 연출: 슬라이스 추가·build, 도주자 실루엣+글리치, 장치 FX, 체포 연출, 관리자 패널·미리보기, 모바일 레이아웃.
- Phase 4 마무리: README/env, deploy TARGETS, `tsc --noEmit`, pytest 전부.
