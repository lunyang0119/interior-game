# Farmhand 조사 보고서 — 로드맵(채집 · 월간 목표 · 정원) 관점 (2026-10-22)

대상: `reference/reference/farmhand` (jeremyckahn/farmhand, GPL v2). 코드는 복사하지 않고 아이디어·데이터 모양·수식·상수만 옮긴다. 경로는 모두 `farmhand/src/` 기준.

## 요약

1. 작물은 `cropTimeline`(단계별 일수 배열) + `tier` 두 값만으로 성장 단계와 가격이 모두 정해진다. 성장은 `daysOld`가 아니라 **물 준 날 수(`daysWatered`)** 로 진행되고, 물을 안 줘도 죽지 않고 멈출 뿐이다. 공유 정원에 그대로 맞는 친절한 규칙이라 도입 추천.
2. 날짜 넘김은 `computeStateForNextDay`의 순수 리듀서 배열 + 알림 누적(`newDayNotifications`)이다. 우리 `settle()`(하루 1회 멱등) 패턴과 1:1로 대응된다.
3. 채집(`forestForageable` 'mushroom' | 'acorn')은 타입과 이미지만 있고 **스폰 로직이 없다**. 채집은 Farmhand가 아니라 우리 광산 `ore_nodes` 모델을 따라 설계해야 한다. 나무의 "한 번 자라고 열매는 짧은 주기로 반복" 모델(`treeTimeline` / `fruitTimeline`)은 지도 위 과일나무 채집점에 쓸 만하다.
4. 업적은 `condition(state, prevState)` + `reward(state)` + `progressAchievement(goal, getter)` 하나로 진행도와 완료가 어긋나지 않게 만든 구조다. 종류는 첫 행동, 누적 매출, 하루 최고 이익, 7일 평균, 품목별 판매량, 정확한 잔액, 첫 희귀 아이템, 10월 한정이다. 월간 목표는 이 모양을 빌리되 진행도를 `events`/`ledger`/`deliveries` SQL로 계산하면 된다.
5. 계절은 15일 주기, 계절별 수요 ±20%, 화면 전체에 CSS `filter` 한 줄이다. 우리는 KST 달력 월로 계절을 정하고, 가격 배수와 카메라 색조만 얹는 정도가 싸다.

---

## 1. 정원 / 작물

### 1.1 작물 데이터 모양 — 도입 추천

- `data/crop.ts:15-39` `crop({cropTimeline, growsInto, tier, ...})`. 씨앗과 열매가 같은 팩토리를 쓰고, 씨앗은 `growsInto`(열매 id 또는 변종 배열)를 가진다. 열매는 `fromSeed(seed)`로 timeline·tier·계절 수요를 물려받는다(`crop.ts:46-73`).
- **가격 공식** `crop.ts:32`: `value = 10 + duration × tier × (isSeed ? 1 : 3)`, `duration = Σ cropTimeline`.
  - 예: 당근 `[2,1,1,1]` tier 1 → 씨앗 15, 열매 25. 토마토 `[2,1,1,1,2,2,2]` tier 3 → 씨앗 43, 열매 109.
  - 열매/씨앗 차익은 `2 × duration × tier`라서 오래 걸리는 작물일수록 하루당 이익이 일정하게 유지된다.
  - → `data/garden.json` 각 작물에 `timeline`, `tier`만 두고 가격은 `server/app/garden.py`에서 같은 꼴의 식으로 계산. 계수(10, 1, 3)는 `garden.json` 상수로.
- **성장 단계** `utils/getLifeStageRange.ts`: timeline 첫 칸은 SEED, 나머지 칸 합은 GROWING, 그 뒤는 GROWN. `utils/getGrowingPhaseForTimeline.ts`는 timeline 몇 번째 칸에 있는지(=스프라이트 프레임 번호)를 돌려준다. timeline 칸 수 = 그림 프레임 수라는 규약이 깔끔하다.
  - → 클라이언트 `room/GardenPlots.ts`가 `phase`로 프레임을 고르고, 서버는 `stage`(seed/growing/grown)만 판정.
- 작물 목록(timeline / tier / 수요 많은 계절) — 참고 수치:

| 작물 | timeline | 합 | tier | 수요 높음 | 수요 낮음 |
|---|---|---|---|---|---|
| carrot | 2,1,1,1 | 5 | 1 | 봄 | – |
| spinach | 2,4 | 6 | 1 | 봄·여름 | 겨울 |
| pumpkin | 3,1,1,1,1,1 | 8 | 1 | 가을 | 봄 |
| potato | 2,1,1,1 | 5 | 2 | 가을·겨울 | 봄·여름 |
| corn | 3,1,1,1,2,2 | 10 | 2 | 여름·가을 | 봄·겨울 |
| onion | 3,1,2,1 | 7 | 2 | – | – |
| wheat | 1,1 | 2 | 3 | – | – |
| tomato | 2,1,1,1,2,2,2 | 11 | 3 | 봄·여름 | 겨울 |
| soybean | 2,2 | 4 | 3 | – | – |
| watermelon | 2,10 | 12 | 4 | 여름 | 가을·겨울 |
| strawberry | 6,2 | 8 | 5 | 여름 | 겨울 |
| grape | 3,4 | 7 | 7 | 봄·가을 | 겨울 |

  우리 게임은 실제 하루가 1틱이라 Farmhand(버튼 한 번 = 하루) 수치를 그대로 쓰면 너무 느리다. 합 2~6일짜리만 골라 쓰거나 timeline을 반으로 줄이는 것이 맞다.

### 1.2 하루 처리 순서 — 도입 추천

`game-logic/reducers/computeStateForNextDay.ts:38-59`. 정원 관련 부분만 순서대로:

1. `processField` (`processField.ts`) — 칸마다 `incrementPlotContentAge` → `resetWasWatered` → `spawnWeeds` → `updatePlotShoveledState`.
   - `incrementPlotContentAge.ts`: `daysOld += 1`; 어제 물을 줬으면 `daysWatered += 1 (+ FERTILIZER_BONUS 0.5, 비료가 있을 때)`.
   - 핵심: **물 준 날 처리 → 물 플래그 초기화**가 같은 패스에서 일어난다. 즉 "어제 물 줬나"로 오늘 성장을 정한 뒤 오늘 물 플래그를 지운다.
2. `processForest` — 나무 나이 증가(1.5절).
3. `processNerfs` → `applyCrows` (까마귀).
4. `processWeather` → `applyPrecipitation` (비 오면 밭 전체 물 주기, 폭풍).
5. `processSprinklers` — 스프링클러 범위 안 작물에 물 플래그. **물 플래그 초기화 뒤에 실행**되므로 "새 날의 물"로 들어간다. 날씨도 마찬가지.
6. 나머지(가격, 재무 기록, 알림 로그 회전).

→ 우리 쪽: `garden.settle(conn, cat, cfg)`를 `main._tick_loop`에 넣고 `room_meta garden_day:<room>`로 하루 1회 멱등. 순서는 Farmhand와 같게 "성장 반영 → 물 초기화 → 날씨/스프링클러가 새 물 플래그 세팅 → 잡초 스폰". 한 번에 여러 날을 건너뛴 경우(서버 다운) 날짜 수만큼 반복하되 날씨는 날짜 시드로 결정적으로.

### 1.3 행동별 규칙과 상수 (`src/constants.ts`)

| 항목 | 위치 | 값 · 규칙 | 판정 |
|---|---|---|---|
| 물 주기 | `reducers/waterPlot.ts` | 작물 칸에만 `wasWateredToday = true`. 중복 무해(멱등) | 도입 추천 → `POST /api/garden/water {x,y}` |
| 비료 | `constants.ts:21` `FERTILIZER_BONUS = 0.5`, `fertilizePlot.ts` | 물 준 날 성장 +0.5일. 칸당 1회. 무지개 비료는 수확 후 같은 씨앗을 재고에서 꺼내 자동 재파종 | 참고만. 우리는 "물 준 날 +1"만으로 시작, 비료는 나중에 상점 아이템 |
| 스프링클러 | `constants.ts:113-114` `INITIAL_SPRINKLER_RANGE = 1`, `processSprinklers.ts`, `utils/getRangeCoords.ts` | 칸에 설치, (2r+1)² 범위 작물 매일 자동 물. 레벨 8·12에서 r +1 | 도입 추천(2차). 공유 정원에서 "아무도 안 들어온 날"을 메우는 장치로 가치가 크다 |
| 수확 | `harvestPlot.ts` | GROWN만. 낫 등급별 수량 1/2/3/4/5. 수확하면 칸 비움. 잡초도 낫으로 수확(value 0.1) | 도입 추천(수량 1 고정으로 시작) |
| 심기 | `plantInPlot.ts` | 빈 칸 + 씨앗 재고. `growsInto`가 배열이면 변종 무작위. 심자마자 스프링클러 재적용 | 도입 추천. 우리는 재고 대신 씨앗값을 공동 자금에서 차감 |
| 잡초 | `constants.ts:360` `WEEDS_SPAWN_CHANCE = 0.15`, `spawnWeeds.ts` | **빈 칸에만** 하루 15% 확률로 잡초. 잡초가 있으면 심을 수 없음 | 도입 추천(가벼운 할 일). 확률은 낮춰서 0.05~0.1 |
| 삽 | `updatePlotShoveledState.ts`, `clearPlot.ts` | 작물을 파내면 `HOE_LEVEL_TO_SEED_RECLAIM_RATE`(0/0.25/0.5/0.75/1) 확률로 씨앗 회수 | 참고만. "작물 뽑기" 권한 설계에만 참고 |
| 까마귀 | `constants.ts:107-108` `CROW_CHANCE = 0.4`, `MAX_CROWS = 5`, `applyCrows.ts` | 허수아비가 밭 어디든 하나 있으면 면제. 아니면 40% 확률로 `floor(rand × (밭확장+1) × 5)`개 작물 파괴 | 참고만. 친구끼리 비동기 게임에서 밤새 작물을 잃는 건 불쾌함만 크다. 쓴다면 "허수아비 하나 놓으면 영구 면제"인 장식 수요 장치로만 |
| 비 | `constants.ts:109` `PRECIPITATION_CHANCE = 0.1`, `applyPrecipitation.ts` | 비 오는 날 밭 전체 물. 알림 1건 | 도입 추천. 날짜 시드로 결정 → 모두에게 같은 날씨, 비 연출(fx) 재사용 |
| 폭풍 | `constants.ts:110` `STORM_CHANCE = 0.5`(비 중) | 피뢰침 없으면 허수아비 파괴, 피뢰침은 내구도(`lightningStrikeCapacity`) 소모 | 무관(처벌성) |
| 계절 수요 | `constants.ts:24-25` ±0.2, `utils/getSeasonalDemandMultiplier.ts` | 작물별 `highDemandSeasons`/`lowDemandSeasons` → 판매가 ×1.2 / ×0.8 | 도입 추천(4절) |
| 가격 변동 | `constants.ts:166` `PRICE_EVENT_CHANCE = 0.2` | 급등/폭락 이벤트 | 참고만 |
| 밭 크기 | `constants.ts:37-49` 6×10 → 8×12(1,000) → 10×16(5,000) → 12×18(20,000) | 돈으로 밭 확장 | 참고만 → 우리는 복구 단계 `unlock`으로 칸 개방 |

### 1.4 공유 정원을 우리 모델에 얹는 안

- **방**: `data/rooms/garden.json`, `kind: "garden"`(`catalog.RoomKind`에 추가). 광산처럼 place/move는 403 `no_place`. 경작 가능한 칸은 방 데이터의 `plots: [[x, y], ...]`(월드 에디터 "밭 칸 칠하기", 벽지 칸과 같은 방식)로 지정.
- **DB** (새 마이그레이션 `018_garden.sql`):
  `garden_plots(room_id, x, y, crop_id, planted_by, planted_day, days_watered REAL, watered_day, ripe_day, weed INTEGER, PRIMARY KEY(room_id, x, y))`.
  - 물 플래그는 불리언 대신 `watered_day`(날짜 키)로 둔다. "오늘 물 줬나" = `watered_day == today`. 초기화가 필요 없어 settle이 단순해지고 재시작에도 안전하다.
- **하루 키**: 손님 정산과 같은 `guests.day_key`(KST 09:00 경계)를 추천한다. 광산은 달력 자정 기준이라 둘 중 하나로 통일 여부를 정해야 한다. "아침에 일어나면 자라 있다"는 연출에는 09:00이 맞다.
- **성장**: `garden.settle()`이 날이 바뀔 때 `watered_day == 어제`인 칸만 `days_watered += 1`. 단계 판정은 순수 함수 `garden.stage(crop, days_watered)`.
- **물 주기**: 아무 플레이어나 `POST /api/garden/water {x, y}`(광산 `reach`처럼 발 위치 근처만). `UPDATE ... SET watered_day = today` 하나라서 동시 요청이 와도 무해하다. 물뿌리개 범위(3×3 등)는 나중에 도구 업그레이드로.
- **심기**: `POST /api/garden/plant {x, y, crop}` → 씨앗값을 `ledger.kind='seed'`로 공동 자금에서 차감, `events.kind='plant'`.
- **수확**: `POST /api/garden/harvest {x, y}` → `UPDATE garden_plots SET crop_id=NULL ... WHERE ... AND stage='grown'` 의 rowcount로 경쟁 처리(광산 hit과 같은 방식). 열매값을 `ledger.kind='crop'`로 수확자 이름으로 적립하고 `ledger_seq` + `deliverable`을 돌려준다. `/api/deliver`에 `kind: "crop"`을 추가하면 복구 단계 `deliver` need에 작물 납품이 바로 들어간다.
- **진행 훅**: 수확·납품은 need를 바꾸므로 같은 트랜잭션에서 `progress.advance_rooms()` 호출, `after_commit()`으로 ws `{"type":"garden"}`를 정원 presence 방에만 보낸다.
- **알림**: settle 결과(익은 작물 수, 비, 잡초)를 `events.kind='garden'` 한 줄로 남기면 기록 패널에 "밤사이 당근 4개가 익었어요"가 뜬다(Farmhand `processForest`의 `FRUIT_READY_TO_HARVEST` 집계와 같은 발상).

### 1.5 여럿이 한 밭을 쓸 때 깨지는 것

| 문제 | Farmhand에서는 | 제안 |
|---|---|---|
| 누가 물을 주나 | 혼자 하니 문제 없음 | 물은 누구나, 멱등. 안 줘도 시들지 않고 멈추기만(Farmhand 규칙 그대로). 비·스프링클러가 빈 날을 메움 |
| 남이 심은 걸 수확 | 해당 없음 | 돈은 어차피 공동 자금이라 "도둑질"이 성립하지 않는다. 대신 이벤트에 `planted_by`와 수확자를 둘 다 남겨 기록 패널에 "안나가 심은 당근을 보리가 수확했어요"처럼 공로를 보이게 |
| 남의 작물 뽑기(그리핑) | 삽으로 파낼 수 있음 | 뽑기는 심은 사람만, 또는 익은 뒤 N일(예: 3일) 방치된 칸만 누구나. 시드 플레이어 규칙처럼 서버가 판정 |
| 씨앗 남발로 자금 고갈 | 해당 없음 | 하루 심기 상한(칸 수 또는 금액) `garden.json daily_plant_cap`. 또는 씨앗값을 작게 두고 열매만 3배 |
| 익은 채 방치 | 작물은 영원히 GROWN | 익은 뒤 `wither_days`(예: 5) 지나면 시든 작물로 바뀌어 칸을 비울 수 있게. 처벌이 아니라 칸 회수용 |
| 동시 수확 | 해당 없음 | 조건부 UPDATE의 rowcount로 한 명만 성공, 나머지는 `already_harvested` |
| 까마귀/폭풍 | 무작위 손실 | 넣지 않음. 넣는다면 허수아비 하나로 영구 면제 |

### 1.6 나무(과일) — 참고만 (정원 2차 또는 채집에 사용)

- `data/tree.ts:20-49`. `treeTimeline`(나무가 다 자랄 때까지, 한 번만), `fruitTimeline`(다 자란 뒤 열매 주기, 수확할 때마다 0으로), `lifespan`(다 자란 뒤 사는 일수).
- 열매값 `tree.ts:30`: `10 + Σ fruitTimeline × tier × 3`. 묘목값 = 열매값 × `SAPLING_FRUIT_CYCLES_TO_BREAK_EVEN = 4`(`tree.ts:18`). 묘목 한 그루가 열매 4번이면 본전이라는 기준이다.
  - 사과: tree `[5,5,5,5,5]`, fruit `[2,2,2]`, tier 2, lifespan 200 → 열매 46, 묘목 184.
  - 바나나: tree `[4,4,4,4,4]`, fruit `[3,3,3,3]`, tier 3 → 열매 118, 묘목 472.
- 수명: 심을 때 한 번 굴려 고정(`utils/getRandomizedLifespan.ts`). 최대 5% 일찍(`TREE_LIFESPAN_VARIANCE_MAX = 0.05`), 넘긴 뒤엔 하루 사망 확률 0.05에서 하루 0.02씩 올라 0.85 상한(`constants.ts:338-346`). **매일 굴리지 않고 심을 때 미리 시뮬레이션해 저장**하는 방식은 서버 재시작·재요청에 안전하다. 우리 랜덤 판정에도 쓸 만한 습관.
- 피커 폴 등급별 열매 1~5개(`constants.ts:323-331`), 도끼 등급별 나무 [1,2]~[8,10], 덜 자란 나무는 범위 절반(`constants.ts:310-318`, `utils/getChopWoodYieldRange.ts`).
- 멀치(`mulchForestPlot.ts`)는 나무 성장을 +0.5 가속하되 수명 계산은 `daysOld` 그대로. 무지개 멀치는 열매 주기도 가속.

---

## 2. 채집

### 2.1 Farmhand에 있는 것

- `farmhand.d.ts:125-128` `forestForageable { daysOld, forageableId: 'mushroom' | 'acorn' }`.
- `utils/getForestPlotImage.ts`가 `forageableId`로 이미지를 고르고, `processForest.ts`가 나이만 올린다.
- **스폰·수확 리듀서가 없다.** `utils/createNewForest.ts`는 빈 칸(null)만 만들고, 어떤 리듀서도 `forestForageable`을 생성하지 않는다. 버섯·도토리 아이템도 `data/items.ts`에 없다. 미완성 기능이다 — 참고만.
- 실제 동작하는 "채집"은 나무 열매(피커 폴)와 벌목(도끼, `wood` value 10)이다.

### 2.2 우리 모델에 얹는 안 — 도입 추천 (Farmhand가 아니라 광산 패턴 기반)

- `data/forage.json` + `server/app/forage.py`. 광산 `ore_nodes`/`mine.ensure_floor()`와 같은 구조로 "KST 하루에 한 번, 첫 요청 때 생성".
- 대상은 지도(`map`)와 정원·여관 마당 같은 바깥 방. 채집점은 `spawns`(에디터로 칠한 후보 칸 목록) 중에서 하루 `per_day`개를 가중치로 뽑는다. 걸을 수 있는 칸만(`tiles.walk`).
- 노드 종류 두 가지:
  - **일회성**(버섯·도토리·꽃): 줍면 사라지고 다음 날 새로 생성. 광산 광석과 동일. `hits: 1`.
  - **재생형**(과일나무·딸기덤불): 지도에 고정 배치. Farmhand의 `fruitTimeline`처럼 `regrow_days` 뒤 다시 열린다. 상태는 `forage_nodes(room_id, x, y, kind, ready_day)` 한 행. 열매 줍기 = `ready_day = today + regrow_days`.
- 보상: 광산과 같게 `ledger.kind='forage'` + `events.kind='forage'`, `ledger_seq` + `deliverable` 반환. `/api/deliver`가 `kind: "forage"`를 받으면 복구 단계 `deliver` need에 바로 쓰인다.
- 1인당 하루 상한(`per_player_day`)을 두면 먼저 접속한 한 명이 다 쓸어가는 문제를 막는다. 공동 자금이라 실익 차이는 없지만, 늦게 온 친구가 할 게 없어지는 것이 더 큰 문제다.
- 계절별 종류 교체(봄 쑥·고사리, 가을 밤·도토리·버섯, 겨울 솔방울)는 4절의 계절 키로 `kinds[].seasons`만 걸면 된다.

---

## 3. 월간 목표 / 업적

### 3.1 업적 구조 — 도입 추천(모양만)

- `data/achievements.ts:61-67` `progressAchievement(goal, getCurrentValue)`가 `condition: s => get(s) >= goal`와 `getProgress: s => ({currentValue, goal})`를 한 getter에서 동시에 만든다. 진행 막대와 완료 판정이 어긋날 수 없다. 우리 `restore.evaluate()`의 `NeedProgress(have, want, done)`과 같은 발상이라 그대로 맞는다.
- 업적 하나 = `{id, name, description, rewardDescription, condition | progressAchievement, reward(state)}`. 리워드 기본값을 IIFE 인자(`(goal = 5000, reward = 25) => ({...})`)로 둬서 수치를 한 곳에서 조정한다.
- `reducers/updateAchievements.ts`는 모든 업적을 돌며 미완료이고 조건을 만족하면 `reward` 적용 + `completedAchievements[id] = true` + 알림. 호출은 상태가 바뀔 때마다(`components/Farmhand/useFarmhand.ts:830`). 한 번 완료하면 끝(월 단위 리셋 개념 없음).

### 3.2 업적 종류 목록

| 종류 | 예시 id (achievements.ts 줄) | 지표 |
|---|---|---|
| 첫 행동 튜토리얼 | plant-crop(71), water-crop(89), harvest-crop(104) | 행동 1회 |
| 누적 매출 | unlock-crop-price-guide(122, 10,000), i-am-rich-1~3(368~392: 50만/100만/10억) | `revenue` 누적 |
| 하루 최고 이익 | daily-profit-1~3(184~220: 5,000/15,000/50,000) | `recordSingleDayProfit` |
| 7일 평균 이익 | profit-average-1~6(232~277: 2,500 ~ 1,000,000) | `record7dayProfitAverage` |
| 품목별 판매량 | sale-goal-1~3(291~314), sell-10000-jack-o-lanterns(172) | `itemsSold[id]` |
| 보관함 확장 | steady-stasher / heavy-hoarder / pro-prepper(326~360) | `inventoryLimit` |
| 정확한 잔액(장난) | lord-of-the-pies(401): 잔액이 정확히 floor(π×10⁶) | `money ==` |
| 첫 희귀 획득 | gold-digger(413): 금광석 첫 획득 | 재고 존재 |
| 채집·벌목 누적 | orchardist(424, 열매 1,000), deforestation(445, 나무 250), landscaper(508, 멀치 100) | 카운터 |
| 제작 누적 | piemaker(436, 파이 100) | `recipesMade` |
| 연승 | farmhand-shuffle-win-streak-1~3 | 미니게임 |
| 계절 한정 | play-during-october(162): 10월에 접속만 하면 잭오랜턴 150개 | `utils/isOctober.ts` = `new Date().getMonth() === 9` |
| 수집 완성 | purchase-all-cow-colors(147) | 종류 수 |

보상 종류: 돈, 경험치, 아이템 묶음, 기능 해금(가격 안내), 영구 판매가 보너스(`I_AM_RICH_BONUSES = [0.05, 0.1, 0.25]`, `constants.ts:184`).

### 3.3 경험치·레벨·업그레이드 — 참고만

- 레벨 `utils/levelAchieved.ts`: `floor(sqrt(xp) / 10) + 1`. 필요 xp `utils/experienceNeededForLevel.ts`: `((L-1) × 10)²` → 레벨 2 = 100, 5 = 1,600, 10 = 8,100.
- xp 값 `constants.ts:369-391` `EXPERIENCE_VALUES` (판매 1, 새 해 5, 대출 상환 25, 시설 구입 10 등). 대부분 "행동 1회 = 소량 xp".
- `data/levels.ts`: 레벨마다 씨앗 해금, 도구 해금(6 삽, 15 도끼+피커 폴+숲), 스프링클러 범위 +1(8, 12). 해금이 없는 레벨은 무작위 씨앗 선물(`processLevelUp.ts`). `utils/getLevelEntitlements.ts`가 레벨까지 누적 해금을 합산.
- `data/upgrades.ts`: 도구별 DEFAULT → BRONZE → IRON → SILVER → GOLD, 각 단계 주괴 8개 + 석탄(주괴별 배수 2/3.5/2.5/3).
- 우리 쪽: 개인 레벨은 공동 자금 게임과 맞지 않는다. 다만 **"모두의 누적 활동량 → 공동 레벨 → 씨앗/채집 종류 해금"** 은 복구 단계의 `unlock` 보상과 겹친다. 별도 레벨 체계 대신 복구 단계 reward에 `unlock_crop` 같은 종류를 추가하는 편이 싸다. 도구 업그레이드는 광산 광석의 쓸모(공동 물뿌리개 범위, 곡괭이 타격 수 감소)로 2차 검토.

### 3.4 공동 월간 목표 후보 10개

기간은 KST 달력 월(`[월초 00:00, 다음 달 월초)`의 `ts` 범위). 모두 기존 테이블로 계산된다.

| # | 목표(예시 문구) | 진행도 계산 |
|---|---|---|
| 1 | 이번 달 물고기 60마리 낚기 | `COUNT(*) FROM events WHERE kind='fish' AND ts BETWEEN ...` |
| 2 | 광석 200개 캐기 | `COUNT(*) FROM events WHERE kind='mine'` |
| 3 | 금 광석 처음 캐기(gold-digger 변형) | `EXISTS events kind='mine' AND item_id LIKE 'gold%'` (월 안) |
| 4 | 납품 30번 하기 | `COUNT(*) FROM deliveries WHERE ts BETWEEN ...` |
| 5 | 손님 40박 받기 | `SUM(json_extract(data,'$.guests')) FROM events WHERE kind='guest'` (없으면 `COUNT`) |
| 6 | 하루 최고 수입 300 찍기(daily-profit 변형) | 날짜 키별 `SUM(amount) WHERE amount > 0 AND kind IN ('fish','mine','guest','forage','crop')`의 MAX |
| 7 | 7일 연속 매일 누군가 수입 올리기(profitability streak 변형) | 위 날짜별 합이 >0인 연속 일수 MAX |
| 8 | 가구 25개 새로 놓기 | `COUNT(*) FROM events WHERE kind='place'` (− 같은 달 remove 상쇄 여부는 선택) |
| 9 | 모두 한 번씩 기여하기 | `COUNT(DISTINCT player_id) FROM events WHERE kind IN (수입 종류)` ≥ 활성 플레이어 수 |
| 10 | 고양이 500번 쓰다듬기 | `SUM(taps) FROM cat_taps WHERE ts BETWEEN ...` |

장난 목표 1개 추가 후보: 공동 자금이 정확히 314가 되는 순간 만들기(lord-of-the-pies 변형, `after_commit`에서 잔액 확인). 10월 한정 목표(호박 수확 N개, 버섯 채집 N개)는 4절 계절 키로 그 달에만 뽑힌다.

**운영 방식 제안**
- `data/goals.json`에 후보 풀을 두고, 매달 첫 settle 때 `room_meta goals:<yyyymm>`에 3개를 뽑아 고정(손님 `dog_month`와 같은 방식). 매달 같은 3개면 지루하니 `pick: 3` + 월별 `force`(10월 = 할로윈) 지원.
- 판정은 순수 함수 `goals.evaluate(goal, counts) -> NeedProgress`, DB 집계는 `goals.counts(conn, month)` 한 번에 SQL 몇 개. `progress.after_commit()`과 분 틱에서 호출하고, 완료 시 `room_meta goal_done:<yyyymm>:<id>` + `events.kind='goal'` + 보상.
- 보상은 공동 자금(`ledger.kind='goal'`, 음수 amount = 자금 증가 규약에 맞춰), 또는 한정 장식 아이템 해금(그 달 목표 3개 달성 시 월 기념 가구). 영구 판매가 보너스(Farmhand `I_AM_RICH_BONUSES`)는 경제를 꼬이게 하니 피한다.
- UI는 기록 패널 `ui/log.ts`에 "이번 달 목표" 섹션 하나(진행 막대 = `have/want`).

---

## 4. 계절 / 달력

- Farmhand: 15일 × 4계절(`constants.ts:23`, `ONE_YEAR_LENGTH_DAYS = 60`), `utils/getCurrentSeason.ts`, `utils/getDayOfSeason.ts`. 1년마다 xp +5(`computeStateForNextDay.ts:74-76`).
- 수요: 작물별 high/low 계절 → ×1.2 / ×0.8(`utils/getSeasonalDemandMultiplier.ts`).
- 화면: `data/seasons.ts:30-38` 계절별 CSS `filter` 한 줄을 스테이지 배경 레이어에 적용(`components/Stage/Stage.tsx:141`). 주석의 요령: `hue-rotate`만 쓰면 픽셀아트의 여러 색이 제각각 돌아가므로 **sepia로 먼저 색 범위를 좁힌 뒤** hue-rotate 해야 한 가지 톤으로 읽힌다.
- 10월: `utils/isOctober.ts`로 실제 달력을 그대로 쓴다.

**우리 쪽 저비용 계절층 — 도입 추천**
- `season.py`의 순수 함수 `season_of(kst_date)`: 3–5월 봄, 6–8월 여름, 9–11월 가을, 12–2월 겨울. 실제 달력이라 상태 저장이 필요 없다.
- 쓰임 세 가지만:
  1. 정원 작물 판매가 ×1.2 / ×0.8(`garden.json crops[].high` / `low`).
  2. 채집 종류 교체(`forage.json kinds[].seasons`).
  3. 지도·바깥 방 카메라 색조. Phaser 3.60+ `camera.postFX.addColorMatrix()`로 `sepia()` → `hue()` 순서를 같은 요령으로 적용. 실내는 손대지 않음.
- 월 한정 이벤트(10월 할로윈, 12월 연말)는 월간 목표 `force` 하나로 처리.

---

## 5. 날짜 처리 파이프라인과 알림

- `computeStateForNextDay.ts:34-79`: `dayCount + 1`, `todaysNotifications = []`로 시작해 리듀서 배열을 `reduce`로 순서대로 통과, 마지막에 `adjustItemValues`. 첫 날은 `processField`만 돌린다(`isFirstDay`).
- 각 리듀서는 사건을 `newDayNotifications`에 `{message, severity}`로 쌓는다(까마귀 `error`, 비 `info`, 열매 익음 `success`).
- 하루가 끝나면 `rotateNotificationLogs.ts`가 그것을 `notificationLog`에 `{day, notifications: {error, info, success, warning}}`로 묶어 앞에 넣고 `NOTIFICATION_LOG_SIZE = 14`일치만 보관(`constants.ts:159`). 화면에는 새 날 시작 때 한 번에 띄운다(`hooks/useFarmhandDayAdvancement.ts:126-142`).
- 서버 메시지(`updateServerForNextDay`)를 먼저 기다린 뒤 로컬 리듀서를 돌린다 — 공유 상태가 로컬 계산보다 앞선다는 순서.

**우리 쪽 대응 — 도입 추천**
- `main._tick_loop`의 분 틱에 `garden.settle`, `forage.ensure_day`, `goals.settle`을 `settle_guests`와 나란히 추가. 각각 `room_meta <kind>_day:<id>`로 하루 1회 멱등, 여러 날 밀렸으면 날짜만큼 반복.
- 순서: 손님 정산 → 정원 성장 → 날씨 → 채집 생성 → 월간 목표 판정. 손님 정산이 먼저여야 그날 숙박 수입이 목표 6·7에 들어간다.
- Farmhand의 "하루 알림 묶음"은 우리 `events`가 이미 맡고 있다. settle마다 사건을 여러 줄 쓰지 말고 **하루 요약 1줄**(`events.kind='garden'`, `data`에 `{ripe: {...}, rain: true, weeds: n}`)로 남기면 기록 패널 5줄 제한(`/api/activity`)을 잡아먹지 않는다.

---

## 로드맵별 제안 데이터 포맷 초안

### `data/garden.json`

```json
{
  "room": "garden",
  "day": "guest",
  "price": {"base": 10, "seed_mult": 1, "crop_mult": 3},
  "daily_plant_cap": 12,
  "wither_days": 5,
  "weed_chance": 0.08,
  "rain_chance": 0.1,
  "reach": 1,
  "crops": [
    {"id": "carrot", "name": "당근", "timeline": [1, 1, 1], "tier": 1,
     "high": ["spring"], "low": [], "sprites": "crop_carrot_", "seed_sprite": "seed_carrot"},
    {"id": "pumpkin", "name": "호박", "timeline": [2, 1, 1, 1], "tier": 2,
     "high": ["fall"], "low": ["spring"], "sprites": "crop_pumpkin_", "seed_sprite": "seed_pumpkin"}
  ]
}
```
가격은 저장하지 않고 `base + Σtimeline × tier × mult`로 계산한다. `sprites`는 접두어이고 `<접두어><phase>` 슬라이스 키를 쓴다. timeline 칸 수와 프레임 수가 같아야 하며, 이는 `catalog` 로드 때 검증한다.

### `data/forage.json`

```json
{
  "rooms": ["map", "garden"],
  "per_day": 12,
  "per_player_day": 6,
  "spawns": {"map": [[12, 30], [13, 30], [40, 8]]},
  "kinds": [
    {"id": "mushroom", "name": "버섯", "value": 8, "weight": 30, "seasons": ["fall"], "sprite": "forage_mushroom"},
    {"id": "acorn", "name": "도토리", "value": 3, "weight": 50, "seasons": ["fall", "winter"], "sprite": "forage_acorn"},
    {"id": "flower", "name": "들꽃", "value": 4, "weight": 40, "seasons": ["spring", "summer"], "sprite": "forage_flower"}
  ],
  "fixed": [
    {"room": "map", "x": 22, "y": 14, "kind": "apple_tree", "yield": "apple", "value": 12, "regrow_days": 3, "sprite": "forage_apple_tree"}
  ]
}
```

### `data/goals.json`

```json
{
  "pick": 3,
  "force": {"10": ["halloween_pumpkin"]},
  "reward": {"pool": 300},
  "goals": [
    {"id": "fish_60", "label": "물고기 60마리 낚기", "metric": "count", "kind": "fish", "want": 60},
    {"id": "deliver_30", "label": "납품 30번 하기", "metric": "deliveries", "want": 30},
    {"id": "best_day_300", "label": "하루에 300 벌기", "metric": "best_day_income", "want": 300},
    {"id": "everyone", "label": "모두 한 번씩 돈 벌어 오기", "metric": "distinct_earners", "want": "all"},
    {"id": "halloween_pumpkin", "label": "호박 20개 수확하기", "metric": "count", "kind": "crop", "item": "pumpkin", "want": 20, "months": [10]}
  ]
}
```
`metric`은 `goals.py`에 있는 정해진 집계 함수 이름이다(count / deliveries / best_day_income / streak_days / distinct_earners / cat_taps). 자유 SQL은 받지 않는다.

---

## 무관한 것

- 소: 사육, 교배, 무지개 소, 우유, 비료 생산, 거래(`processCow*`, `cow*`)
- 저장고·발효·와인(`processCellar*`, `makeWine`, `KEG_*`, `WINE_*`)
- 요리·대장간·재활용 레시피(`data/recipes.ts`, `makeRecipe`) — 광석 사용처를 고민할 때만 다시 볼 만함
- 대출과 이자(`adjustLoan`, `applyLoanInterest`)
- Farmhand Shuffle 카드 미니게임
- P2P 피어 동기화와 가격 이벤트 브로드캐스트(`addPeer`, `updatePeer`, `*PriceEvent*`)
- 보관함 한도·확장, 콤바인, 퇴비통, 우드칩퍼, 제련소 구입
- 밭 채굴(`minePlot`, `RESOURCE_SPAWN_CHANCE`, 광석 확률) — 우리 광산이 이미 더 정교함
- 폭풍·피뢰침(처벌성 이벤트), 알림 스낵바 지속시간, localForage 저장
