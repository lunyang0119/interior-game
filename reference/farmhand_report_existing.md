# Farmhand 조사 보고서: 기존 컨텐츠 관점

대상: `reference/reference/farmhand` (jeremyckahn/farmhand, GPL v2). 코드는 복사하지 않는다. 아래 경로는 모두 farmhand 저장소 기준이며, 아이디어, 상수, 공식만 옮겨 재구현한다.

## 요약

- 채굴은 우리 쪽이 훨씬 풍부하다. Farmhand의 채굴은 "밭 칸을 삽으로 한 번 파면 확률로 광석 1개, 칸은 며칠 쿨다운" 수준이다. 가져올 것은 **희귀도에 비례한 쿨다운**과 **도구 등급이 스폰 확률을 올리는 구조** 정도다.
- 낚시는 없다. 대신 **스트림 이름별 난수 큐(queueRandomNumbers)** 가 우리 bite schedule과 광산 레이아웃 테스트에 그대로 쓸 만한 패턴이다.
- 경제에서 가장 쓸 만한 것은 **품목별 시세 계수 0.5~1.5 + 하루 단위 랜덤 재생성 + 폭등/폭락 이벤트(며칠 고정)** 다. 서버 권위 모델인 우리에게 더 잘 맞는다. Farmhand는 클라이언트가 계수를 보고하므로 신뢰성이 없다.
- 알림은 "오늘의 알림(중복 제거) → 날이 바뀌면 severity별로 묶어 일자 로그에 push, 최대 14일" 구조다. 우리 `events` 테이블 + 기록 패널에 **하루 요약 묶음**을 얹는 아이디어로 쓸 수 있다.
- P2P(Trystero) 동기화와 소 교환 핸드셰이크는 우리 서버 권위 모델과 무관하다. 테스트 쪽은 `testState` 팩토리, 업적 condition/progress 단일 소스, 한 리듀서 한 파일 ADR이 참고할 만하다.

## 1. 채굴 / 광석

**Farmhand 모델**

- 스폰 2단계 가중 추첨이다. 먼저 `RESOURCE_SPAWN_CHANCE = 0.3`(`src/constants.ts:279`)으로 "뭔가 나오는지"를 굴리고, 삽 등급이 그 확률에 더한다. BRONZE +0.1, IRON +0.2, SILVER +0.3, GOLD +0.5 (`src/factories/ResourceFactory.ts:103-115`). 다음으로 종류를 ORE 0.25 / COAL 0.15 / STONE 0.4 가중치로 뽑고(`constants.ts:284-286`), ORE이면 BRONZE 0.4 / IRON 0.33 / SILVER 0.2 / GOLD 0.07로 다시 뽑는다(`constants.ts:292-295`, `src/factories/OreFactory.ts`).
- 가치는 stone 10, coal 2, bronze 25, iron 40, silver 100, gold 500이다(`src/data/ores/*.ts`). gold는 스폰 기여 0.3×0.25×0.07 ≈ 0.5%로 매우 희귀하고, 값은 bronze의 20배다. 우리 tier(gold 90, silver 40)는 이보다 훨씬 평평하다.
- **희귀도 비례 쿨다운**이 있다. 판 칸은 `[1,2,2,3]`일 중 하나로 막히고, 무언가 나왔으면 `round(random() * (1 - minSpawnChance) * 10)`일을 더한다(`src/game-logic/reducers/minePlot.ts:12,37-48`). 희귀한 광석일수록 그 칸이 오래 쉰다.
- 제련과 도구 업그레이드가 광석의 소비처다. 주괴 1개 = 광석 5 + 석탄 5/12/8/10(bronze/iron/silver/gold), 해금 조건은 "그 광석을 50개 판매"(`src/data/recipes.ts:719-776`). 삽, 괭이 등 업그레이드는 주괴 8~15개 + 석탄을 소모한다(`src/data/upgrades.ts:123-138`).
- 일일 리셋은 없다. 칸별 쿨다운만 있다.

**우리와의 비교와 판단**

- **도구 등급이 확률을 올리는 구조: 참고만.** 우리는 공용 풀 경제라 개인 도구 등급을 두면 "누가 캐도 같은 풀" 원칙과 충돌한다. 공용으로 쓰려면 "광산 곡괭이 업그레이드"를 복원 stage 보상(`restore.py` reward)으로 두고, `data/mine.json`에 `pickaxe_levels: [{hits_mult, ladder_chance_add}]`를 두는 식이 맞다.
- **희귀도 비례 비용: 도입 추천(형태 변경).** 우리는 하루 단위 재생성이라 "칸 쿨다운"은 필요 없다. 대신 같은 아이디어를 `hits`에 반영할 수 있다. 지금 gold_wall은 hits 4, value 90이다. Farmhand처럼 값 대비 노력을 희귀도에서 유도하려면 `mine.py` 로드 시 `hits` 미지정 ore에 `hits = 1 + round((1 - weight_share) * k)`를 계산해 주는 기본값을 두면 tier 가중치를 바꿀 때 밸런스가 자동으로 따라간다. 단순 수동 표가 더 읽기 쉽다면 생략해도 된다.
- **판매 누적 해금: 참고만.** "bronze를 50개 팔면 다음 레시피 해금"은 우리 복원 stage의 `deliver` need(`kind: mine`)와 같은 역할이다. 이미 있다.
- **값의 폭: 참고만.** Farmhand는 최고 광석이 최저의 20~50배다. 우리 bronze 15 → gold 90은 6배다. 깊은 층(16~20)에 내려갈 동기를 키우고 싶다면 gold를 150~200으로 올리고 tier 4의 gold 가중치를 낮추는 쪽이 Farmhand식 "드물지만 크게"다.

## 2. 낚시 / 타이밍 / 랜덤 이벤트

- **낚시 없음: 확인.** `src/` 전체에 fish 언급이 없고 GAME_DESIGN_DOCUMENT.md에도 없다. 타이밍 기반 미니게임도 없다. 유일한 미니게임은 카드 셔플 내기(`placeFarmhandShuffleWager.ts`, `settleFarmhandShuffleMatch.ts`)인데 낚시와 관계없다.
- **`applyChanceEvent`(`src/game-logic/reducers/helpers.tsx:39`): 참고만.** `[(확률 판정 함수, 리듀서)]` 배열을 순서대로 reduce하는 3줄짜리 헬퍼다. 날씨(`processWeather.ts:7`), 까마귀(`processNerfs.ts:5`)에 쓰인다. 우리 `guests.settle()`이나 일일 틱에 "랜덤 이벤트 목록"이 생기면 같은 모양(`[(chance_fn, apply_fn)]`)으로 두면 된다. 지금은 필요 없다.
- **스트림 이름별 난수 큐: 도입 추천.** `src/common/services/randomNumber.ts`의 `RandomNumberService`는 `generateRandomNumber(stream)`이 그 스트림에 큐된 값이 있으면 먼저 꺼내고, 없으면 seed 또는 `Math.random`으로 돌아간다. `queueRandomNumbers('precipitation', [0])`로 "오늘 밤 비"를 강제한다. 스트림 이름은 `randomStream` enum(`src/enums.ts:320-335`)으로 고정되어 있다.
  - 우리 대응: `fishing.Fishing.rng`와 `mine.layout_floor(rng=)`는 이미 `random.Random`을 주입받는다. 다만 한 rng에서 loot, gap, window, hold를 순서대로 뽑으므로 "loot만 chest로 고정" 같은 테스트는 seed 탐색이 필요하다. `server/app/rng.py`에 `class Streams(random.Random)` 하나를 두고 `pick(stream, ...)`이 큐 값을 먼저 쓰게 하면, `test_fishing.py`/`test_mine.py`에서 `rng.queue("loot", [chest])`, `rng.queue("ladder", [0.0])`로 의도를 직접 쓸 수 있다. dev 라우터(`routers/dev.py`)에 같은 큐를 노출하면 디버그 계정이 "다음 캐스트 보물상자"를 재현할 수 있다.
- **가격 이벤트를 bite에 응용: 무관.** bite schedule은 이미 서버가 judge하므로 Farmhand에서 더 가져올 판정 로직은 없다.

## 3. 경제

**Farmhand 모델**

- **시세 계수.** `doesPriceFluctuate: true`인 품목마다 `valueAdjustments[id] ∈ [0.5, 1.5)`이다. 매일 `random(stream) + 0.5`로 새로 뽑는다(`src/common/utils.ts:15-27`, 날 넘김 `computeStateForNextDay.ts`의 `adjustItemValues`). 판매가 = 기본가 × 계수(`src/utils/getItemCurrentValue.ts`). 광석은 stone/coal 빼고 모두 변동, stone은 고정이다.
- **공유 시장(서버).** `api-src/post-day-results.ts:29-50` `applyPositionsToMarket`. 클라이언트가 하루 동안의 품목별 순포지션(+1 순매수/보유 증가, −1 순매도, `src/utils/computeMarketPositions.ts`)을 보내면, 서버가 `variance = random() * 0.2`만큼 계수를 올리거나 내리고 [0.5, 1.5]로 자른다. 경계에 붙은 채 변화가 없으면 `random() + 0.5`로 다시 흔든다. Redis 키는 room 이름별이다(`api-etc/utils.ts getRoomData`). 즉 "다 같이 팔면 값이 떨어진다."
- **폭등/폭락 이벤트.** 하루에 `PRICE_EVENT_CHANCE = 0.2`(`constants.ts:166`) 확률로 해금된 작물 하나에 crash(계수 0.5 고정) 또는 surge(1.5 고정)를 50:50으로 건다(`generatePriceEvents.ts`). 기간은 그 작물 생육일 − 1일이다(`getPriceEventForCrop.ts`). 매일 `daysRemaining`을 1씩 줄이고 0이면 삭제한다(`updatePriceEvents.tsx`). 이벤트는 새날 알림으로도 나간다. 주의할 점으로, 이벤트는 각 플레이어 로컬 state라 같은 방 친구들끼리도 다르다.
- **대출.** 시작 대출 500, 일이자 2%, 판매 수익에서 5% 원천징수(`constants.ts:16-19`, `sellItem.ts`, `applyLoanInterest.ts`).
- **기타 배수.** 계절 수요 ±20%(`constants.ts:24-25`, `getSeasonalDemandMultiplier.ts`), 업적 "부자" 단계별 판매가 +5/10/25%(`I_AM_RICH_BONUSES`, `getSalePriceMultiplier.ts`).
- **온라인 보너스.** 접속 중이면 10초마다 `money += activePlayers`(`useFarmhandNetwork.ts` heartbeat, `HEARTBEAT_INTERVAL_PERIOD`). 같이 접속할수록 돈이 는다.
- 중복 아이템 판매가 감쇠는 Farmhand에 없다. 우리 `comfort.py`의 duplicate decay가 이미 그 역할을 한다.

**우리에게 맞는 저비용 안**

- **물고기/광석 일일 시세: 도입 추천.** 우리는 서버 권위이고 KST 게스트 날(09:00)과 광산 날이 이미 있다. 그래서 Farmhand의 "클라이언트가 포지션을 보고"하는 신뢰 문제 없이 같은 효과를 낼 수 있다.
  - 상태: `room_meta price:<loot_id>` 또는 새 테이블 `market(day, kind, item_id, mult)`.
  - 생성: 하루 첫 틱(`main._tick_loop`, 광산 리셋 시점)에 `mult = 0.5 + rng.random()`이다. 너무 출렁이면 `0.8 + 0.4*rng.random()`으로 폭을 줄인다.
  - 수요 반영: Farmhand의 포지션 규칙을 서버 데이터로 대체한다. 어제 그 품목의 `ledger kind in (fish, mine)` 건수가 평균보다 많으면 `−variance`, 적으면 `+variance`로 클램프한다. 클라이언트 보고가 필요 없다.
  - 적용: `fishing.finish` / `mine.hit`에서 `value × mult`를 원장에 쓴다. `deliver` 환불도 같은 금액을 쓰도록 ledger 금액을 그대로 되돌리면 된다(이미 그렇게 동작).
  - 노출: `/api/activity`에 `market {id: mult}`를 붙이고, 기록 패널에 "오늘 시세" 한 줄을 둔다.
- **폭등/폭락 이벤트: 도입 추천(위와 같이).** 하루 20%로 loot/ore 하나를 ×1.5 또는 ×0.5로 2~3일 고정하고, `events.kind='market'` 한 줄로 공지한다. 공용 풀이라 "오늘 참돔 폭등" 같은 공지가 모두의 행동을 한쪽으로 모으는 재미가 생긴다. 의도적으로 ×0.5는 빼고 surge만 두는 것도 고려할 만하다. 공용 풀에서 손해 이벤트는 재미가 적다.
- **대출/이자: 무관.** 수입원이 구글 시트 실적이라 빚 구조가 맞지 않는다.
- **온라인 보너스: 참고만.** "동시 접속자 수만큼 소액 적립"은 공유 월드 동기 부여로 그럴듯하다. 그러나 시트 기반 화폐의 의미(실제 실적)를 흐리므로 넣는다면 cat affection처럼 비화폐 수치에 적용하는 편이 낫다.

## 4. 알림 / 활동 로그

**Farmhand 모델**

- `showNotification(state, message, severity, onClick?, actionLabel?)`(`src/game-logic/reducers/showNotification.ts`)는 토스트용 `latestNotification`을 설정하고, 같은 메시지가 오늘 이미 있으면 `todaysNotifications`에 다시 넣지 않는다(중복 제거, 29-33행).
- 날 넘김 단계들은 `newDayNotifications`에 `{message, severity}`를 쌓는다(가격 이벤트, 대출 잔액 등).
- `rotateNotificationLogs`(`rotateNotificationLogs.ts`)는 그날의 새날 알림을 severity별 배열 `{error, info, success, warning}`로 묶어 `{day, notifications}` 한 항목으로 로그 맨 앞에 넣고, 길이를 `NOTIFICATION_LOG_SIZE = 14`(`constants.ts:159`)로 자른다.
- 부팅 시 저장된 새날 알림을 `setTimeout(…, 0)`으로 하나씩 토스트로 흘린다(`useFarmhand.ts:634-641`).
- 문구는 `templates.ts`의 `(_, …args) => string` 함수로 모은다. 복수형, 목록 줄바꿈("Your cows produced milk:\n  - 3 Milk")을 템플릿 안에서 처리한다. 고정 문구는 `strings.ts`다.
- 상태 비교형 알림도 있다. `useFarmhandNotifications.ts`는 이전/현재 state를 비교해서 "인벤토리가 방금 꽉 참", "레시피 1개 / 여러 개 배움"을 한 번만 띄운다.
- 피어 메시지는 `pendingPeerMessages`(최대 5)를 메타데이터에 실어 보내고, 받는 쪽은 `latestPeerMessages`(최대 30)에 prepend한다(`prependPendingPeerMessage.ts`, `updatePeer.ts`).

**우리에 대한 판단**

- **하루 요약 묶음: 도입 추천.** 우리 `/api/activity`는 최신 5행만 준다(`routers/activity.py:38`). 이미 `events`가 kind별로 쌓이고 같은 파일에서 kind별 SUM/COUNT도 계산한다(54-57행). Farmhand식으로 "게스트 날(09:00 KST) 하나 = 요약 1행"을 만들면 된다. 예: "어제: 낚시 12번 340, 채광 8번 210, 손님 3팀 450". 이렇게 하면 5행 제한 안에서 오래된 활동도 보인다. 저장은 하지 말고 `events`에서 `GROUP BY day, kind`로 계산하면 마이그레이션이 필요 없다. 보관 길이 14일은 그대로 써도 된다.
- **토스트 중복 제거: 도입 추천(작음).** 같은 메시지 토스트가 짧은 시간에 반복되면 무시한다. 예로 광산 `floor_locked`, 낚시 `fish_cooldown` 연타가 있다. 클라이언트 토스트 함수에 `last message + ts` 비교 한 줄을 두면 된다.
- **severity 4단계: 참고만.** 우리 토스트 스타일(`docs/conventions/ui.md`)에 info/success/warning이 없다면, 로그 아이콘 색만 severity로 나누는 정도가 적당하다.
- **템플릿 함수 모음: 참고만.** 우리 문구는 한국어 해요체라 복수형 처리는 필요 없다. 다만 "여러 개면 목록, 하나면 한 문장"(RECIPE_LEARNED / RECIPES_LEARNED) 분기는 손님 메모나 하루 요약에 쓸 만하다.
- **상태 비교형 알림: 참고만.** 우리는 서버가 `events`로 이미 이 역할을 한다.

## 5. 멀티플레이

- **구조.** Trystero(WebRTC) 방에 접속하고, `PEER_METADATA_STATE_KEYS`(`constants.ts:252`)에 있는 통계 몇 개와 교환용 소를 메타데이터로 브로드캐스트한다(`src/utils/getPeerMetadata.ts`). 시장 계수만 Vercel + Redis 서버에 있다(`api-src/get-market-data.ts`, `post-day-results.ts`).
- **소 교환 핸드셰이크**(`src/handlers/peer-events.ts`). A가 B의 "교환 제안 소"를 요청한다. B는 자기 state에서 그 소가 아직 제안 중인지, 다른 교환을 기다리는 중이 아닌지 확인한다. 그다음 자기 쪽 인벤토리를 바꾸고 `sendCowAccept`를 보낸다. 실패하면 `sendCowReject {reason}`을 보낸다. 성공 후 750ms 기다렸다가 저장한다. 원주인에게 돌아오면 `timesTraded`를 올리지 않는다.
- **신뢰성.** 사실상 없다. 각자 로컬 state가 진실이고, 시장 포지션도 클라이언트가 보고한다. 누구든 계수를 밀 수 있다.
- **우리에 대한 판단: 무관.** 우리는 단일 서버 Hub(`presence.py`)와 서버 판정(낚시 judge, mine hit reach)이 이미 있다. P2P 메타데이터 방송, 교환 핸드셰이크, 하트비트 활성 인원 집계는 전부 필요 없다. "핸드셰이크 중 상대 상태 재검증 후 거절 이유 코드 반환" 패턴은 우리 REST 403/409 코드 체계와 같은 생각이고, 이미 있다.

## 6. 테스트 / 코드 구성

- **한 리듀서 한 파일 + 짝 테스트(`doc/adr/0002-one-reducer-per-file.md`): 참고만.** 우리는 서버가 이미 "순수 규칙 모듈(`placement.py`, `restore.py`, `comfort.py`) + DB 모듈(`progress.py`, `guests.py`)" 분리를 쓰고, 테스트는 모듈 단위다. 파일을 더 쪼갤 이유는 없다.
- **`testState(overrides)` 팩토리(`.rules` 1-120행, `src/test-utils/`): 도입 추천.** "부분 state를 손으로 만들지 말고 항상 완전한 기본값 + overrides"가 핵심 규칙이다. 우리 `server/tests/conftest.py`에도 픽스처가 있지만 `test_mine.py`(20K), `test_guests.py`(17K), `test_train.py`(56K)가 크다. `make_ore_cfg(**over)`, `make_floor(rocks=…, nodes=…)`, `make_guest_room(items=…)` 같은 작은 팩토리를 conftest에 모으면 테스트가 짧아진다.
- **업적 condition/progress 단일 소스(`src/data/achievements.ts:61` `progressAchievement(goal, getCurrentValue)`): 도입 추천.** 하나의 `getCurrentValue`에서 "완료 여부(≥ goal)"와 "진행 막대(current/goal)"를 함께 만들어 둘이 어긋날 수 없게 한다. 우리 `restore.py`의 need 평가(`deliver`, `pool`, `placed`)와 게시판(`ui/board.ts`)의 진행 표시가 같은 관계다. 각 need 평가가 `(current, goal)`을 반환하고 `done = current >= goal`로 파생되게 하면, 다음 "월간 목표" 기능도 같은 함수 하나로 쓸 수 있다. 이미 그렇게 되어 있다면 확인만 하면 된다.
- **난수 스트림 큐: 도입 추천.** 2절 참조. README "Debugging"(63-73행)의 `window.farmhand.queueRandomNumbers(...)`처럼 dev 전용 훅으로 노출하는 것까지 포함한다.
- **`window.farmhand` 디버그 훅(README 65-71행): 참고만.** `window.farmhand.state` / `setState`를 dev 빌드에서만 노출한다. 우리 클라이언트는 `state.ts`가 공유 상태이니 `import.meta.env.DEV`일 때 `window.game = { state, bus }`를 붙이는 정도는 비용이 거의 없다.
- **클라이언트 테스트.** Farmhand는 React Testing Library와 vitest를 쓴다(ADR 0001). 우리에게 클라이언트 테스트가 없으니 가장 가치 있는 시작점은 `client/src/room/rules.ts`(서버 `placement.py` 미러)를 vitest로 서버와 같은 케이스로 돌리는 것이다. Farmhand에서 직접 가져올 것은 없다.

## 7. UI (ADR 0007)

- **9-slice 프레임.** Farmhand는 3×3/4×4 텍스트 픽셀맵에서 SVG를 런타임 생성해 `border-image`로 쓴다. 색은 팔레트에서 오고, bevel은 inset `box-shadow`, 배경은 `background-clip: padding-box`로 모서리 투명을 지킨다. **참고만.** 우리는 이미 PNG 9-slice + `ui_theme.json` 생성 파이프라인이 있다(`docs/conventions/ui.md` 23-28행). 하나 가져올 규칙이 있다. "프레임 요소 배경을 바꿀 때 `background` 단축 속성 대신 `backgroundColor`를 쓴다. 단축 속성이 `background-clip`을 리셋해 투명 모서리 밑을 칠한다." 우리 `style.css`의 `button.primary { background: var(--primary); … }`(178행)가 이 함정에 해당할 수 있으니 프레임이 켜진 테마에서 모서리를 확인할 것.
- **`font-synthesis: none`: 도입 추천(한 줄).** 픽셀 폰트에 가짜 bold/italic이 생기면 격자가 뭉개진다. 우리 `style.css`와 `client/src`에 이 선언이 없다. `body`에 추가하면 된다. Stardust에 bold 페이스가 없다면 bold 지정 텍스트가 regular로 나오는 것을 감수해야 한다.
- **`size-adjust`로 폰트 교체 시 레이아웃 유지: 참고만.** 우리는 폰트 크기 5단계 변수와 모바일 별도 값을 이미 가진다. 폰트를 바꿀 일이 생기면 그때 쓴다.
- **픽셀 아이콘을 텍스트 맵으로: 무관.** 우리는 `data/ui_icons.json` → 스프라이트 PNG 파이프라인이 있다.
- **"액션 있는 알림은 Alert 전체 대신 버튼을 클릭 가능하게"(안드로이드에서 눌린 상태가 남는 버그): 참고만.** 우리 토스트에 클릭 동작을 붙일 때 같은 원칙을 지키면 된다.
- **툴팁 화살표 금지, blur 그림자 금지: 무관.** 이미 우리 픽셀 규칙과 같다.
- 모바일 대응은 MUI 반응형 수준이고, 우리 `(max-width: 899px), (pointer: coarse)` 분기보다 특별한 것은 없다.

## 바로 해볼 만한 것 Top 5

1. **물고기/광석 일일 시세 계수.** 서버가 KST 하루마다 품목별 `mult ∈ [0.5, 1.5)`를 뽑는다. 어제 `ledger` 판매량으로 ±0.2 이내 보정한다. `fishing.finish`/`mine.hit` 원장 금액에 곱한다. Farmhand `generateValueAdjustments` + `applyPositionsToMarket`을 서버 데이터만으로 재구현하는 것이다.
2. **폭등 이벤트.** 하루 20% 확률로 loot/ore 하나를 ×1.5로 2~3일 고정하고 `events.kind='market'`으로 공지한다. 1번 위에 얹는 작은 추가다(Farmhand `generatePriceEvents`/`updatePriceEvents`).
3. **스트림별 난수 큐.** 서버 `random.Random` 래퍼에 `queue(stream, values)`를 둔다. `test_fishing.py`/`test_mine.py`에서 loot, ladder, ore 결과를 seed 탐색 없이 고정하고, dev 라우터로 디버그 계정에도 노출한다(Farmhand `RandomNumberService`).
4. **기록 패널 하루 요약.** `events`를 KST 게스트 날 단위로 `GROUP BY kind` 해서 "어제: 낚시 N번 +X, 채광 …, 손님 …" 한 줄을 만든다. 14일까지 보여 주고, 마이그레이션은 필요 없다(Farmhand `rotateNotificationLogs`).
5. **진행도 단일 소스 + 테스트 팩토리.** 복원 need 평가를 `(current, goal)` 반환으로 통일해 완료 판정과 게시판 진행 막대를 한 함수에서 만든다. 아울러 conftest에 `make_*(**overrides)` 팩토리를 모은다(Farmhand `progressAchievement`, `testState`).

## 무관한 것

- P2P(Trystero) 방, 피어 메타데이터 방송, 하트비트 활성 인원 집계, 소 교환 핸드셰이크.
- Vercel 서버리스 + Redis 시장 API 구조와 CORS 처리.
- 대출/이자/원천징수.
- 계절 수요 배수(우리에게 계절 개념이 없다).
- 칸별 채굴 쿨다운(우리는 층 전체가 하루 단위로 재생성된다).
- 픽셀 아이콘 텍스트 맵, SVG 생성 프레임(우리 PNG 파이프라인이 이미 대체한다).
- 카드 셔플 내기 미니게임, 소/와인/셀러/숲 시스템 전반.
- localforage 저장, state import 변환(`transformStateDataForImport`).
