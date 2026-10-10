# 안락도 · 손님 · 숙박료 설계 (2026-10-09)

기획서 `261008_plan_1.md` §4-A를 수치와 데이터 구조까지 내린 것. **같은 날 구현됨** — 아래 §1~§3은 `server/app/comfort.py`·`guests.py`·`data/guests.json`과 일치. 구현에서 달라진 점: 손님 수 구간은 `score // 34 + 1`(10–33→1, 34–67→2, 68+→3); 예약 테이블은 `reservations(id, room_id, kind, item_id, due_day, created_ts, status, pay)`; 개파 손님 예약은 매달 첫 정산 때 `room_meta dog_month`로 1회 생성(그 달 날짜가 이미 지났으면 건너뜀); 손님 NPC가 걸어다니는 연출·상점 링크는 아직 없음(§6 2차). **구역(2026-10-09 추가)**: 방의 `zones`(에디터 "구역 그리기")가 있으면 구역 하나하나가 손님 단위(키 `방:구역`), K는 구역 넓이, 세트·침대·예약도 구역별. 구역 밖 가구는 점수에 안 들어감. 구역이 없는 방은 방 전체가 단위라 기존 동작 그대로. 상수는 전부 `data/guests.json`에 두고, 판정은 `restore.py`처럼 DB 없는 순수 함수(`server/app/comfort.py`)로 만든다.

## 0. 한 줄 요약

방의 **안락도(0–100)** = 배치한 가구 가격의 포화 합 × 세트 보너스 − 부서진 가구 페널티 (+ 나중에 고양이 애착).
매일 KST 09:00 "체크아웃"에 방마다 **손님 수 = min(침대 수, 안락도 구간)**, **1인 숙박료 = 4 + 0.36 × 안락도**를 공동 자금에 넣는다. 침대(`bed` 태그) 없으면 손님 0.

## 1. 안락도 (comfort) — 순수 함수

입력: 방 `items`(DB 행), 카탈로그, 설정. 출력: `Comfort {score, beds, raw, set, set_share, set_items, ruined, dup_loss}` (+ `.public()`).

### 1.1 집계 대상
- `placed_by != '$seed'` 이고 `ruined` 태그가 없는 아이템만 점수에 들어간다. 시드 가구는 "???"라 플레이어 노력이 아니므로 제외. (여관 시드에 침대가 있어도 **침대 수에는 센다** — 침대 요건은 "방에 침대가 있는가"이므로.)
- `ruined` 아이템은 점수 대신 페널티로만 작용.
- 모든 레이어 포함(벽지·바닥도 산 거니까). 단 **세트 판정은 `furniture` + `surface_item`만**(타일 시트는 가구 시트와 절대 안 겹쳐서 세트 점유율을 깎기만 함).

### 1.2 가격 합 (중복 감쇠)
같은 `item_id`의 n번째 사본은 `price × dup_decay^(n−1)` (`dup_decay = 0.5`). 의자 10개 도배 방지, 2~3개는 거의 온전히 인정.

`raw = Σ price_i × dup_decay^(k_i)`

### 1.3 포화 (방 크기 보정)
`K = cols × rows × k_per_cell` (`k_per_cell = 0.5`) → 여관(26×22) K≈286, 2층(41×31) K≈636.

`base = 100 × raw / (raw + K)`

- raw = K → 50점. 여관에 60💰 가구 5개 ≈ 50점. 100점은 못 찍고 85~90이 현실적 상한 → 손님 3명 구간은 "진짜 꾸민 방"에만.
- 큰 방일수록 더 채워야 하는 게 자연스럽고, 방마다 상수를 손볼 필요 없음.

### 1.4 세트 보너스
`set` = 빌드 파이프라인이 슬라이스의 원본 시트 경로에서 만든 슬러그(§4). 가구·소품을 `set`별 가격 합으로 묶고, 최대 세트의 점유율 `share = max_set_sum / furn_sum`.

- 최대 세트의 아이템이 `set_min_items = 4`개 미만이면 보너스 없음.
- `mult = 1 + set_bonus_max × clamp((share − 0.5) / 0.5, 0, 1)` (`set_bonus_max = 0.5`) → 절반까지는 보너스 0, 전부 한 세트면 ×1.5.
- `scored = base × mult` (100 캡은 마지막에).

### 1.5 페널티·가산
- `ruined` 1개당 `ruined_penalty = 5` 감점. 여관 초기(junk 11개)는 −55라 청소 전엔 사실상 0 → 복구 단계와 자연스럽게 맞물림.
- 고양이(기획 I) 구현 시 `+ affection × 3` (0~9). 여기서 훅만 남긴다. → 2026-10-10 구현: affection = 모두가 합쳐 쓰다듬은 횟수 ÷ 100(최대 3, 영구 누적).
- `score = clamp(round(scored − penalty + bonus), 0, 100)`

### 1.6 침대
`beds` = `bed` 태그 아이템 수(시드 포함, ruined 제외). `beds == 0` → 손님 0, UI에 "침대가 없어요". 침대가 많을수록 손님 상한이 올라감(최대 3명 구간까지).

## 2. 손님과 숙박료 — 일일 정산

### 2.1 시각과 멱등성
- 하루 경계: KST `checkout_hour = 9`. `day_key = (now_kst − 9h).date().toordinal()`.
- `room_meta guest_day:<room>` = 마지막으로 정산한 day_key. 정산은 `guests.settle(conn, cat, now)` 한 함수, 몇 번 불러도 같은 날엔 한 번만.
- 호출 위치: ① 기동 시(`advance_rooms` 뒤) ② lifespan의 60초 주기 asyncio 태스크(`PRUNE` 태스크와 같은 꼴, `asyncio.to_thread` + 새 conn). 시트 스레드와는 무관.
- 서버가 며칠 꺼져 있었으면 **빠진 날은 최대 `max_catchup_days = 3`일까지** 현재 안락도로 정산(그 이상은 "손님이 안 온 날"). 이유: 재시작 한 번에 돈이 왕창 들어오는 걸 막으면서 하루 이틀 장애는 봐줌.

### 2.2 대상 방
잠기지 않은 격자 방 전부(`locked`에 없는 `cat.rooms`). 잠긴 방은 손님 없음. 방별로 독립 정산.

### 2.3 손님 수
```
if beds == 0 or score < min_comfort(10): guests = 0
else: guests = min(beds, ceil(score / band(34)))   # 10–33 → 1, 34–67 → 2, 68–100 → 3
```

### 2.4 숙박료
`per_guest = round(pay_base(4) + pay_per_comfort(0.36) × score)` → 20점 11💰, 50점 22💰, 85점 35💰.
`pay = guests × per_guest` (예약·개파 손님은 §3에서 가산).

스케일 감각: 가구 1~60💰, 물고기 5~200💰, 시트 벌이 수백~천 단위, 2단계 풀 요구 1000. 여관 하나 50점·침대 2 → 하루 44💰, 세 방을 80점대로 올리면 하루 300💰 안팎. 일주일 꾸미면 풀 1000을 채우는 속도. 과하면 `pay_per_comfort`만 내리면 됨.

### 2.5 기록
- `ledger (kind='guest', amount=−pay, item_id='room:<id>')` — 잔액 공식(`earned − Σledger`)은 그대로.
- `events (kind='guest', room_id, amount=+pay, data={guests, per_guest, score, reserved, dog})`. 📜 문장: "여관에 손님 2명이 묵고 44💰를 냈어요".
- `/api/activity`의 `today.earned`는 시트 벌이만 세고 있으므로 `today.guests`(숙박료 합)를 따로 추가.
- 커밋 후 `money` 브로드캐스트 + `after_commit`(event 행). 접속 중이면 토스트.

## 3. 예약 손님 · 개파 손님

### 3.1 테이블
```
reservations(id PK, room_id, kind 'item'|'dog', item_id NULL, due_day INT, created_ts, status 'pending'|'paid'|'missed'|'skipped', pay INT)
```
`room_meta no_guests_day:<room>` = 손님이 안 오는 day_key(놓친 예약 다음날).

### 3.2 예약 생성 (정산 끝에, 방마다)
- 그 방에 `pending`이 없고, `beds ≥ 1`, 주사위 `reservation.chance = 0.25`.
- `due_day = today + randint(lead_days 2..4)`.
- 요구 아이템: 구매 가능(ruined/fixed/note/stairs 아님), `furniture`|`surface_item`, `price ≥ 10`, **방에 아직 없는 것**. 70%는 그 방의 최대 세트에서, 30%는 전체에서 뽑는다(세트 보너스와 같은 방향으로 유도).
- 이벤트 `reserve`: "손님이 예약했어요 — 🪑 {가구} 를 D-3까지 준비해 주세요". 📜 패널 방 섹션에 예약 카드(가구 아이콘·남은 날·가격). 상점에서 해당 아이템 하이라이트는 2차.

### 3.3 예약 판정 (due_day 정산 때)
- 아이템이 방에 있음(시드 제외, ruined 아님) → 예약 손님 1명 추가로 `per_guest × reservation.pay_mult(2)`. 침대는 침대 수와 무관하게 1명 더 받음(예약이니까). `status='paid'`, 이벤트 "예약 손님이 와서 2배(44💰)를 냈어요!"
- 없음 → `status='missed'`, `no_guests_day:<room> = due_day + 1`, 이벤트 "예약 손님이 실망해서 돌아갔어요. 내일은 손님이 안 와요". 다음날 정산에서 그 방은 guests = 0 (이벤트 "오늘은 손님이 없었어요").
- 방이 그새 잠길 일은 없음(잠김은 단조 감소). 요구 아이템을 due 전에 팔면 missed.

### 3.4 개파 손님 (월 1회)
- 매달 1일 정산에서 **안락도가 가장 높은 방** 하나에 `kind='dog'` 예약 생성, `due_day` = 그 달 안의 날(월별 시드 난수, 1~28일 중 ≥ +3일). 이벤트 "개를 좋아하는 손님이 {날짜}에 온대요".
- due 정산: 방에 `dog` 태그 아이템(강아지 인형·개집 등, 유저가 태깅) 있음 → `per_guest × dog.pay_mult(3)`; 없어도 `score ≥ dog.comfort_fallback(70)` 이면 옴(같은 3배); 둘 다 아니면 `skipped`, **페널티 없음**(기획: 낮으면 그냥 안 옴).

## 4. 선행 작업 (파이프라인·태깅)

1. **`set` 슬러그**: `build`가 각 슬라이스의 `sheet`(원본 경로)에서 슬러그를 만들어 manifest에 `set`으로 넣고, `catalog.public()`이 `items[].set`으로 내보냄. 규칙: 파일 stem 소문자 → `Theme_Sorter/4_Bedroom_16x16` → `mi_bedroom`, `PPFurniture Pack-FreeV` → `ppfurn`, `pi_livingroom_lrk` 등은 `config.py`의 `SET_ALIASES` 표로 묶음(`pi_*_lrk` → `pi_living`, `pi_*_br` → `pi_bedroom`, `pi_*_ba` → `pi_bath`). 슬러그에 `sheet`가 절대 들어가지 않게 테스트 추가(카탈로그 `sheet` 금지 규칙). 시트 66개 → 세트 40개 안팎.
2. **태그**(유저, 에디터 아이템 탭 `iTags`): `bed`(지금 진행 중), 나중에 `dog`.
3. `data/guests.json` 신설 + `catalog.load`에서 검증.

## 5. 서버 구조

- `server/app/comfort.py` (순수): `comfort(cat, room, items, cfg, affection=0) -> Comfort`, `guest_count`, `pay_per_guest`, `pick_reservation_item(cat, room_items, rng)`.
- `server/app/guests.py` (DB): `settle(conn, cat, now)`(멱등, 트랜잭션 안), `room_guest_view(conn, cat, room)` → `{score, beds, guests, per_guest, reservation, no_guests}`.
- `routers/room.py` `GET /api/rooms`: 방별 `comfort` 뷰 추가(ETag 없는 엔드포인트라 안전). `/api/activity`에도 동일 뷰.
- `migrations/009_guests.sql`: `reservations` + 인덱스. `room_meta` 키 추가(`guest_day:`, `no_guests_day:`).
- 배치·이동·삭제 후 안락도는 저장하지 않음(요청 때 계산, 아이템 수백 개라 싸다). `progress` ws 메시지에 `comfort`를 같이 실어 보내면 클라 갱신 공짜.

## 6. 클라이언트

- 📜 패널 방 섹션: 안락도 바(0–100) + 내역 3줄("가구 62 · 세트 ×1.3 · 부서진 가구 −10"), 침대 수, "내일 예상: 손님 2명 · 44💰", 예약 카드.
- HUD 방 칩: `여관 · 1/2단계` 옆에 `☕42` 정도. 숫자 하나만.
- 토스트: 정산·예약·미스 이벤트(이미 `event` 채널 있음).
- 손님 NPC가 실제로 걸어다니는 건 2차(캐릭터 생성기로 외형, 체크인 시간대에만 방에 있음).

## 7. 테스트 계획

- 순수: 빈 방 0 / 시드 제외 / 중복 감쇠 / 포화 K / 세트 보너스 경계(share 0.5, 1.0, 최소 4개) / ruined 페널티 / 캡 100 / 침대 0 → 손님 0 / 구간 경계 33·34·67·68.
- DB: 같은 날 두 번 settle → 한 번만; 3일 공백 → 3번; 10일 공백 → 3번; 잠긴 방 제외; ledger·events·잔액 일치; 예약 생성→충족→2배; 미충족→다음날 0명; 개파 폴백 70점.

## 8. 열어둔 것

- 정산 시각 09:00 vs 자정 — 아침에 접속했을 때 "밤새 손님이 다녀갔다"가 보이도록 09:00 추천.
- 손님 수 상한 3명 고정 vs 침대 수만큼 — 침대 5개 방이 5명 받게 하려면 `band`를 안락도 대신 "침대 1개당 안락도 25점 필요"로 바꾸면 됨. 1차는 3명 캡.
- 예약 요구 아이템을 상점에서 바로 찾아가는 링크(📜 카드 → 상점 열고 검색어 입력)는 UI 2차.
