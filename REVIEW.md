# 코드 리뷰: QoL · 처리 속도

> **2026-09-25 반영 상태**: 표의 모든 항목 반영 완료 (P1-0 ~ P3-8). 서버 pytest 19개 통과, 클라이언트 `tsc`·`vite build` 통과, 헤드리스 크롬으로 러그 위 아바타·구운 타일 렌더 확인.
> 반영 방식 메모: P2-5는 배치바의 `+1` 버튼(놓고 같은 가구를 하나 더), P2-6은 흐려진 행을 누르면 프리셋을 자동으로 끄는 방식, P2-7은 마우스 hover 추적 + footprint 칸 표시 + 스테퍼 길게 누르면 자동 반복.

기준: `main` 07cc9ed (2026-09-25). 서버 `server/app/**`, 클라이언트 `client/src/**`, 배포 `deploy/**` 전체를 읽고 정리했다.
클라우드 울트라리뷰(최근 diff 대상)에서 나온 항목 2개도 포함했다 (P3-1, P3-2).

우선순위 기준
- **P1**: 사용자가 체감하는 버그성 동작 / 특정 조건에서 요청이 수 초 멈춤
- **P2**: 반복 조작에서 매번 거슬리는 것, 폰에서 프레임·배터리에 영향
- **P3**: 작은 정리, 누수, 문구

---

## 요약표

| # | 우선순위 | 영역 | 내용 | 파일 |
|---|---|---|---|---|
| P1-0 | P1 | 버그 | 러그(floor)가 그 위에 선 아바타를 덮음. 러그도 "footprint 맨 아래 줄"로 y-정렬돼서 러그 위쪽 칸에 선 아바타보다 깊이가 커짐 | `client/src/room/depth.ts`, `room/ItemLayer.ts`, `room/Placement.ts` |
| P1-1 | P1 | 속도 | 시트 캐시 만료 시 첫 요청이 Apps Script 응답(최대 10초)을 동기로 기다림. 락도 그동안 잡혀 다른 요청까지 줄줄이 대기 | `server/app/sheet.py:110`, `routers/me.py:29`, `routers/room.py:46` |
| P1-2 | P1 | QoL | 다른 사람이 가구를 사면 내 잔액·상점 disabled 표시가 안 바뀜 (공용 풀인데 방만 갱신) | `server/app/routers/room.py:25`, `client/src/scenes/RoomScene.ts` |
| P1-3 | P1 | QoL | 러그(floor)·벽지(wall) 위를 탭하면 걷지 않고 메뉴가 뜸. 러그 깔린 방에서는 그 칸으로 못 감 | `client/src/scenes/RoomScene.ts:185`, `room/ItemLayer.ts:itemAt` |
| P2-1 | P2 | 속도 | 배치 모드에서 포인터가 움직일 때마다(같은 칸이어도) 규칙 검사 + bus 이벤트 + DOM 갱신(`closeAllPanels`, `querySelectorAll`) | `client/src/room/Placement.ts:49-72`, `ui/hud.ts:47` |
| P2-2 | P2 | 속도 | 요청마다 SQLite 새 연결 + PRAGMA 3개 + `last_seen_ts` UPDATE(쓰기 락) | `server/app/db.py:52`, `auth.py:76` |
| P2-3 | P2 | 속도 | 가구 놓기/이동/삭제 뒤 `/api/room` 전체를 두 번 받아옴 (내 `room:refresh` + WS `room` 브로드캐스트) | `client/src/room/Placement.ts:confirm`, `scenes/RoomScene.ts:bindSocket` |
| P2-4 | P2 | 속도 | 상점 패널은 잔액이 바뀔 때마다 썸네일 69개를 캔버스로 다시 그림 | `client/src/ui/shop.ts:76` |
| P2-5 | P2 | QoL | 가구 하나 놓으면 상점이 닫혀서 여러 개 놓으려면 매번 다시 열어야 함 | `client/src/ui/hud.ts:47`, `room/Placement.ts:confirm` |
| P2-6 | P2 | QoL | 프리셋 켜진 상태에서 흐려진 머리/피부/눈 행이 눌리고, 값이 몰래 바뀜. 나중에 프리셋 끄면 엉뚱한 조합이 나옴 | `client/src/ui/avatarEditor.ts:82-100` |
| P2-7 | P2 | QoL | 배치 고스트가 손가락을 뗀 상태(마우스 hover)에서는 안 따라옴. 2×2 이상 가구는 어느 칸을 차지하는지 안 보임 | `client/src/scenes/RoomScene.ts:174`, `room/Placement.ts` |
| P2-8 | P2 | 속도 | `/gen`, `/media`, `/assets` 정적 파일에 `Cache-Control` 없음 → 머리 스타일 넘길 때마다 304 왕복 | `server/app/main.py:41-46`, `deploy/Caddyfile` |
| P2-9 | P2 | 속도 | WS 브로드캐스트가 클라이언트 순서대로 `await` → 한 명 느리면 모두 지연 | `server/app/presence.py:58` |
| P3-1 | P3 | 누수 | `contextmenu` 리스너가 계정 전환(scene.restart)마다 캔버스에 누적 (울트라리뷰) | `client/src/scenes/RoomScene.ts:160` |
| P3-2 | P3 | 누수 | `access_log`, 레이트리밋 버킷이 무한 성장 | `server/app/auth.py:41`, `ratelimit.py` |
| P3-3 | P3 | 속도 | 바닥·벽 타일 280개를 개별 Image로 유지. RenderTexture 하나로 굽기 가능 | `client/src/scenes/RoomScene.ts:70` |
| P3-4 | P3 | 속도 | 아바타 레이어 프레임 복사를 매 프레임 `setFrame(name)`으로 (문자열 조회) | `client/src/avatar/Avatar.ts:98` |
| P3-5 | P3 | 속도 | `/api/catalog`가 요청마다 pydantic `model_dump` 69개 재직렬화 | `server/app/catalog.py:78` |
| P3-6 | P3 | QoL | 저장·등록·동기화 버튼 더블 탭 방지 없음 (place만 `busy` 가드 있음) | `ui/avatarEditor.ts`, `ui/accounts.ts`, `ui/hud.ts` |
| P3-7 | P3 | QoL | 긴 토스트도 2.2초에 사라짐. 토큰 만료 안내는 다 읽기 전에 사라짐 | `client/src/bus.ts:toast`, `main.ts:33` |
| P3-8 | P3 | 문구 | 반말 남은 곳: `"돈이 부족해"`, `prompt("복구 링크 (복사해)")`. rate_limited 문구의 "10분"은 실제 한도(분당 120)와 안 맞음 | `ui/shop.ts:53`, `ui/accounts.ts:35`, `api.ts:12` |

---

## P1

### P1-0. 러그가 아바타를 덮는다 (고침)

깊이는 `sortRow * 100 + z`이고 `sortRow`는 footprint의 맨 아래 줄이었다. 3줄짜리 러그가 5~7줄에 깔리면 깊이 700, 그 위 5줄에 선 아바타는 515라 러그가 앞으로 온다.
러그·벽지는 애초에 어떤 것과도 겹쳐 그려질 일이 없으므로 줄과 무관하게 항상 바닥에 붙여야 한다.
고친 내용: `depth.ts`에 `sortRowFor(layer, bottomRow)`를 두고 floor/wall은 `-1`을 돌려준다(깊이 -100). 바닥 타일은 `TILE_DEPTH = -1000`으로 내려 러그 아래에 깔린다. 배치 고스트도 같은 함수를 쓴다.

### P1-1. 시트 동기화가 요청 스레드를 막는다

`SheetService.refresh()`는 `self._lock`을 잡은 채로 `httpx.get(..., timeout=10.0)`을 부른다.
`/api/me`(앱 켤 때마다), `/api/room/place`(구매마다)가 이걸 호출하므로, 60초 캐시가 만료된 뒤 첫 요청은 Apps Script 응답 시간(보통 1~3초, 최악 10초)만큼 멈춘다.
그 사이 들어온 다른 사람의 `/api/me`·구매도 락 때문에 같이 대기한다. 워커 1개, 스레드풀 40개라 서버 전체가 죽진 않지만 "가끔 구매 버튼이 몇 초 안 눌리는" 체감이 여기서 나온다.

고치는 방법 (권장 순):
1. **백그라운드 갱신**: `lifespan`에서 `asyncio` 태스크 하나가 `SHEET_CACHE_SECONDS`마다 `refresh(force=True)`를 돌리고, 요청 경로에서는 `refresh()` 호출을 빼고 스냅샷만 읽는다. `/api/sync`만 즉시 갱신. 요청은 항상 SQLite 조회로만 끝난다.
2. 최소 수정: 락 안에서는 "지금 누가 fetch 중인가"만 판단하고, 네트워크 호출은 락 밖에서 한다. 이미 stale인 스냅샷을 그대로 돌려주고(stale-while-revalidate) fetch는 별도 스레드에 던진다.

주의: 구매 시 잔액 검사는 `sheet.balance(conn)`을 트랜잭션 안에서 하므로, 백그라운드 갱신으로 바꿔도 이중 지출은 막힌다 (`BEGIN IMMEDIATE`가 잡혀 있음).

### P1-2. 공용 잔액이 다른 사람 행동에 안 따라온다

잔액은 모두가 공유하는 풀인데, 서버는 방 변경 시 `{"type":"room","version"}`만 보낸다. 클라이언트는 방 아이템만 다시 받고 잔액은 그대로 둔다.
결과: A가 5000짜리를 사면 B의 HUD 잔액과 상점의 disabled 표시는 B가 뭔가 살 때까지 옛날 값이다. B가 그 상태로 구매를 누르면 서버에서 `insufficient_funds`가 떠서 "왜 안 되지"가 된다.

고치는 방법: `_notify()`에 잔액을 같이 실어 보낸다.

```python
# routers/room.py
def _notify(version: int, balance: int) -> None:
    hub.broadcast_threadsafe({"type": "room", "version": version, "balance": balance})
```

클라이언트 `socket.on("room")`에서 `state.balance = m.balance; bus.emit("money", ...)`. `WsMsg` 타입에 `balance?: number` 추가.
시트 동기화(`/api/sync`)로 잔액이 바뀐 경우도 같은 메시지를 쏘면 모두 일관된다.

### P1-3. 러그·벽지 위를 탭하면 걷지 못한다

`POINTER_UP`에서 `itemAt(cx, cy)`가 truthy면 메뉴를 연다. `itemAt`은 floor(러그)·wall(벽지)도 포함하므로, 러그 위 칸은 전부 "메뉴 여는 칸"이 된다. 방 바닥을 러그로 채우면 걸어갈 데가 없다.

고치는 방법: 탭은 furniture/surface_item에만 반응하고, floor/wall은 길게 누르기로만 메뉴를 연다.

```ts
// RoomScene.ts POINTER_UP
const hit = this.items.itemAt(cx, cy);
const tappable = hit && (this.cat.byId.get(hit.item_id)?.layer !== "floor" && ... !== "wall");
if (tappable && this.openMenu(...)) return;
```

`itemAt`에 `layers?: Set<Layer>` 인자를 주는 편이 깔끔하다. 길게 누르기 경로(`openMenu` 직접 호출)는 지금처럼 모든 레이어를 본다.

---

## P2

### P2-1. 배치 모드 포인터 이동마다 전부 다시 계산

`Placement.pointer()` → `setCell()` → `checkPlace()`(blocked Set 재생성, 다른 아이템 전부 footprint 계산) → `publish()` → `bus.emit("place:state")` → hud에서 `show()` ×2, `textContent`, `classList.toggle`, `closeAllPanels()`(`querySelectorAll`).
폰에서 드래그하면 `POINTER_MOVE`가 초당 60~120번 온다. 칸이 안 바뀌어도 매번 다 돈다.

고치는 방법:
```ts
pointer(wx, wy) {
  const a = anchorUnderPointer(...);
  if (a.cx === this.cell.cx && a.cy === this.cell.cy) return;  // 같은 칸이면 끝
  this.setCell(a.cx, a.cy);
  this.publish();
}
```
`publish()`도 label/ok가 이전과 같으면 emit을 생략한다. 이것만으로 배치 중 DOM 작업이 사실상 0이 된다.
추가로 `checkPlace`의 `blocked` Set은 카탈로그 로드 시 한 번 만들어 두면 된다 (`makeCatalog`에 `blockedSet` 추가).

### P2-2. 요청마다 SQLite 연결 + 쓰기

`get_db()`가 요청마다 `sqlite3.connect` + `PRAGMA journal_mode/foreign_keys/busy_timeout`을 실행한다. 여기에 `current_player`가 매 요청 `UPDATE players SET last_seen_ts`를 한다. 이건 WAL 쓰기 락을 잡는 작업이라, 누가 가구를 놓는 트랜잭션 중이면 단순 `GET /api/me`도 `busy_timeout`까지 기다릴 수 있다.

고치는 방법:
- `last_seen_ts`는 60초에 한 번만 갱신 (`WHERE last_seen_ts < ?` 조건을 붙이면 대부분 no-op).
- 연결은 `threading.local()`로 스레드당 하나 재사용. 스레드풀이 40개라 연결도 최대 40개.
- 읽기 전용 라우트(`/api/room`, `/api/catalog`)는 `current_player`를 안 거치므로 이미 쓰기가 없다. 그대로 두면 된다.

### P2-3. 방 스냅샷 이중 fetch

구매 성공 → `bus.emit("room:refresh")`로 한 번, 서버 WS `room` 브로드캐스트(본인 포함)로 한 번. 두 요청이 거의 동시에 나가서 첫 번째가 `state.roomVersion`을 갱신하기 전에 두 번째가 출발하므로 ETag 304도 못 받는다.

고치는 방법: `refreshRoom()`을 in-flight 프로미스로 합친다.
```ts
private inflight: Promise<void> | null = null;
refreshRoom() {
  if (this.inflight) return this.inflight;
  this.inflight = this.doRefresh().finally(() => { this.inflight = null; });
  return this.inflight;
}
```
더 나아가면 서버가 `room` 메시지에 변경된 행 자체(`{op:"place", item:{...}}`)를 실어 보내 fetch 자체를 없앨 수 있다. 방 아이템이 수백 개가 되기 전까진 in-flight 합치기로 충분하다.

### P2-4. 상점 썸네일 재생성

`bus.on("money")`마다 `render()` → 69개 캔버스 생성 + `drawImage`. 잔액은 구매마다, 그리고 P1-2를 고치면 다른 사람 구매마다 바뀐다.
고치는 방법: 아이템 요소를 한 번 만들고(`Map<itemId, HTMLElement>`), 잔액 변화 시에는 `classList.toggle("disabled", price > balance)`만 돌린다. 탭 전환은 `display` 토글. 스크롤 위치도 유지된다.

### P2-5. 연속 배치가 번거롭다

`place:state`가 active가 되면 `closeAllPanels()`가 상점을 닫는다. 놓기 → 상점 → 스크롤 → 다음 아이템의 반복.
고치는 방법 중 하나:
- 놓기 성공 후 상점을 자동으로 다시 연다 (직전 탭·스크롤 유지, P2-4와 같이 하면 자연스럽다).
- 또는 배치바에 "하나 더" 버튼: 같은 아이템 고스트를 다시 띄운다. 벽지·러그처럼 여러 개 까는 아이템에 특히 좋다.

### P2-6. 프리셋 켜진 상태에서 흐려진 행이 눌린다

`.off`는 `opacity: .4`뿐이고 스테퍼 핸들러는 그대로 동작한다. 사용자는 아무 변화가 없는 걸 보고 몇 번 더 누르게 되고, `draft.hair` 등이 보이지 않게 바뀐다.
고치는 방법 (더 나은 UX): 흐려진 행을 누르면 **프리셋을 자동으로 "없음"으로 돌리고** 그 조작을 적용한다. "레이어를 만지면 커스텀 모드로 전환"이 직관적이다. 단순히 막고 싶으면 `stepper()`에 `disabled` 플래그를 넘겨 `onStep`을 건너뛴다.

### P2-7. 고스트 조작

- `POINTER_MOVE`에서 `p.isDown`일 때만 고스트가 따라온다. 폰에선 맞지만 데스크톱에서는 마우스를 움직여도 고스트가 spawn에 멈춰 있어 "고장난 것처럼" 보인다. 포인터 타입이 mouse면 hover도 따라가게 한다 (`p.pointerType === "mouse" || p.isDown`).
- 2×2, 3×2 가구는 어느 칸에 걸리는지 안 보인다. 고스트 아래 footprint 칸에 반투명 사각형(`Graphics` 하나 재사용)을 그리면 충돌 원인이 바로 보인다. 색은 지금 틴트와 같은 OK/BAD 두 가지.
- 머리 스타일 463개처럼 스테퍼 반복이 많은 곳은 버튼 길게 누르면 자동 반복(`setInterval` 120ms)을 넣으면 손이 덜 간다.

### P2-8. 정적 파일 캐시 헤더

Starlette `StaticFiles`는 `ETag`/`Last-Modified`만 붙이고 `Cache-Control`은 안 붙인다. 브라우저는 `/gen/chars/hair/123.png`를 다시 볼 때마다 304 왕복을 한다. 아바타 편집기에서 머리를 넘길 때, 방에 새 사람이 들어올 때 매번 RTT가 붙는다.
고치는 방법: Caddy에서 처리하는 게 제일 싸다.
```
@static path /gen/* /media/* /assets/*
header @static Cache-Control "public, max-age=86400, stale-while-revalidate=604800"
```
`/assets/index-*.js`는 해시가 붙으니 `immutable, max-age=31536000`으로 더 길게. `/gen/*`은 preprocess 재실행 시 내용이 바뀔 수 있으니 하루 정도. 완전히 안전하게 하려면 `manifest.json`에 build id를 넣고 URL에 `?v=`를 붙인다.

### P2-9. WS 브로드캐스트 직렬화

`Hub.broadcast()`가 클라이언트마다 `await send_text`를 순서대로 한다. 한 명의 소켓 버퍼가 차 있으면(폰 화면 꺼짐, 터널 등) 뒤 사람들 이동 패킷이 전부 늦어진다. 이동은 초당 10회 × 인원이라 금방 티가 난다.
고치는 방법: `asyncio.gather(*[asyncio.wait_for(o.ws.send_text(data), 2.0) ...], return_exceptions=True)`. 타임아웃 난 소켓은 dead 처리.

---

## P3

### P3-1. contextmenu 리스너 누적
`bindInput()`이 `this.game.canvas.addEventListener("contextmenu", ...)`를 하는데 `teardown()`에서 안 뗀다. 계정 전환마다 하나씩 쌓인다. 핸들러를 필드에 저장해 `removeEventListener`하거나, `main.ts`에서 게임 생성 직후 한 번만 등록한다.

### P3-2. 무한 성장하는 테이블·딕셔너리
- `access_log`: 구매·이동·삭제·sync·auth 실패마다 한 줄. 잘못된 토큰으로 두드리면 무제한으로 커진다. `lifespan`에서 하루 한 번 `DELETE FROM access_log WHERE ts < now - 90d`.
- `RateLimiter._buckets`: 키가 지워지지 않는다. `allow()`에서 마지막 접근이 `per_seconds * 2` 넘은 항목을 가끔 정리.

### P3-3. 바닥 타일 280개
`drawRoom()`이 20×14 Image를 만든다. 텍스처가 같아 드로우콜은 배칭되지만 매 프레임 280개 오브젝트를 순회·컬링한다. `this.add.renderTexture(0,0,W,H)`에 한 번 `draw`하고 원본 Image는 버리면 오브젝트 1개가 된다. 저사양 폰에서 아바타 여럿 움직일 때 여유가 생긴다.

### P3-4. 레이어 프레임 동기화
`Avatar.update()`가 매 프레임 `setFrame(driver.frame.name)`을 호출한다. 프레임 이름은 숫자 문자열이라 텍스처의 프레임 맵을 매번 문자열로 찾는다. `driver.frame`이 직전과 같으면 건너뛰고, 바뀔 때만 `setFrame(driver.frame)` (Frame 객체 직접 전달)로 한다. 레이어 4~5개 × 아바타 N명 × 60fps라 작지만 공짜다.

### P3-5. 카탈로그 응답 캐시
`catalog.public()`이 요청마다 pydantic dump를 한다. 로드 시 한 번 dict를 만들어 두고, `ETag`도 붙여 두면 앱 재시작 없이는 304로 끝난다. 앱 진입 시 첫 요청이라 체감은 작다.

### P3-6. 더블 탭 가드
아바타 저장, 등록, 토큰 재발급, 동기화 버튼은 응답이 오기 전에 다시 눌린다. 등록은 서버가 `already_registered`로 막지만 토스트가 두 번 뜬다. 공통 헬퍼 하나로 해결된다.
```ts
function guard(btn: HTMLButtonElement, fn: () => Promise<void>) {
  btn.addEventListener("click", async () => { if (btn.disabled) return; btn.disabled = true; try { await fn(); } finally { btn.disabled = false; } });
}
```

### P3-7. 토스트 길이
`toast(text, ms = 2200)`. 토큰 만료 안내(약 50자)나 등록 완료 안내는 읽기 전에 사라진다. 기본값을 글자 수에 비례시키면 된다: `ms ?? Math.min(6000, 1500 + text.length * 60)`.

### P3-8. 문구
- `ui/shop.ts:53` `"돈이 부족해"` → `"돈이 부족해요"` (인게임 문구는 해요체 규칙).
- `ui/accounts.ts:35` `prompt("복구 링크 (복사해)")` → `"복구 링크예요. 복사해 주세요"`.
- `api.ts:12` rate_limited 문구의 "10분이 이상적"은 실제 한도(플레이어당 분당 120회, 등록 IP당 분당 5회)와 맞지 않는다. "잠시 후 다시 시도해주세요" 정도로.

---

## 잘 되어 있는 부분 (건드리지 않아도 됨)

- 방 스냅샷 ETag + WS 버전 알림 + 소켓 끊겼을 때만 60초 폴링. 트래픽 설계가 깔끔하다.
- `BEGIN IMMEDIATE` 트랜잭션 안에서 규칙 검증 + 잔액 검사 + INSERT. 동시 구매 레이스가 없다.
- 아바타 시트를 필요한 레이어만 지연 로드하고 텍스처 캐시를 확인한다. 머리 463개를 다 안 받는다.
- 배치 규칙이 서버(`placement.py`)와 클라이언트(`rules.ts`)에 같은 구조로 있어 고스트 색과 서버 판정이 일치한다.
- 320×224 캔버스를 FIT로 확대하는 구조라 GPU 부담이 거의 없다.

## 추천 착수 순서

1. P1-2 (잔액 브로드캐스트) + P1-3 (러그 탭) — 각각 20줄 이내, 체감이 가장 크다.
2. P2-1 (같은 칸 스킵) + P3-1 (리스너) — 10줄, 폰 드래그가 바로 가벼워진다.
3. P1-1 (시트 백그라운드 갱신) — 서버 구조 변경이라 테스트(`tests/test_api.py`의 sync 케이스) 손봐야 한다.
4. P2-8 (Caddy 캐시 헤더) — 배포 설정 3줄.
5. 나머지는 손 가는 대로.
