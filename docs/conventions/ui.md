# UI 규칙 (DOM UI)

현재 코드가 실제로 하는 방식을 정리한 문서다. 새 규칙을 만들지 않는다. 바꾸기 전에 여기와 코드를 같이 본다.
Phaser 캔버스 안의 그림은 다루지 않고, `client/index.html` + `client/src/ui/*.ts` + `style.css`만 다룬다.

## 파일 역할

- `client/index.html`: 모든 패널, HUD, 바의 DOM이 정적으로 들어 있다. 패널을 JS로 만들지 않는다.
- `client/src/style.css`: 기본 토큰 + 레이아웃. 요소별 스타일은 `#id .class` 형태로 한 파일에 쌓는다.
- `data/ui_theme.json` -> `preprocess.py ui` -> `client/public/media/theme.css` + `media/ui/*.png`: 색, 폰트, 프레임을 덮어쓴다 (`tools/preprocess/README.md` "UI 스킨 바꾸기").
- `theme.css`는 생성물이다. 직접 고치지 않는다. index.html은 `style.css` 다음에 `theme.css`를 로드한다.

## 색과 폰트 토큰

- 색은 CSS 변수만 쓴다: `--bg --panel --chip --card --text --muted --primary --danger` (`style.css:5-12`). 기본값은 어두운 테마이고, `ui_theme.json`의 `colors`가 같은 이름으로 덮어쓴다 (`theme.css`는 `html:root`로 specificity를 이긴다, `preprocess.py:1196`).
- 역할: `--panel` 패널/큰 버튼, `--chip` 칩과 기본 버튼, `--card` 패널 안쪽 카드와 입력, `--muted` 보조 글씨, `--primary` 강조(선택 윤곽, 진행 바, primary 버튼).
- 패널 안쪽 카드의 표준 모양: `background: var(--card); border-radius: 10px; padding: 8px 10px; margin-bottom: 6px` (`.ev`, `.guest`, `.rsv`, `.quest`, `.acct`, `.shop-item`가 모두 같다). 현재 위치 강조는 `outline: 2px solid var(--primary)` + `.here`/`.active`.
- 하드코딩 색은 상태 표시에만 남아 있다. 변수로 바꾸지 말고 같은 값을 재사용한다: 성공 `#7cc67c`, 경고/실패 `#e07070`, 낚시 노랑 `#ffd35c`, 연결 끊김 `#b03a3a`, 단계 완료 배경 `rgba(255, 211, 92, .14)`, 손님 `rgba(120, 200, 140, .14)`, 놓침 `rgba(230, 110, 110, .14)` (`style.css:51`, `:104-116`, `:218`). 이 값들은 테마를 따라가지 않는다 (알려진 부채).
- 글꼴: `--font-body`(테마에서 Stardust 픽셀 폰트). 크기 단계는 5개뿐이다: `--font-size`(본문) `--fs-small`(보조, 안내, 카드 속 설명) `--fs-button`(일반 버튼) `--fs-big`(하단 큰 버튼) `--fs-title`(패널 제목). 새 글씨 크기가 필요하면 이 중에서 고른다.
- 예외: `11px`가 `.when`, `.credits`, `.note-foot`에 직접 박혀 있다 (`style.css:81`, `:163`, `:176`). 이 정도 작은 보조 글씨만 허용되는 관행이다.
- 모바일 크기: `(max-width: 899px), (pointer: coarse)`에서 `ui_theme.json`의 `font.sizes_mobile`이 적용된다 (현재 small 13 / button 15 / big 20 / title 18 / preview 120, 데스크톱은 20 / 16 / 40 / 30 / 160). 생략하면 `preprocess.py:1257`이 데스크톱 값을 상한으로 깎는다. 하단 큰 버튼이 화면을 먹지 않게 하려는 장치다.

## 9-slice 프레임

- 프레임 이름 8개: `panel button button_primary chip input ctx toast note`. 각 이름마다 변수 4개 `--frame-X --slice-X --slice-X-px --pad-X`가 있고 기본은 `none`/0 (`style.css:14-21`).
- 적용 요소(`preprocess.py FRAME_SELECTORS`): panel -> `.panel`, button -> `button, button.big`, button_primary -> `button.primary`, chip -> `.chip`, input -> `input`, ctx -> `#ctx`, toast -> `#toast`, note -> `.note-paper`.
- 동작: 프레임 변수가 없으면 둥근 기본 모양, 있으면 `border-image: var(--frame-X) var(--slice-X) fill round`로 PNG가 늘어나고, 생성된 `html .panel { border-radius: 0; background: none; ... }` 규칙이 둥근 모양을 끈다. 요소 쪽 CSS는 항상 `border: var(--slice-X-px) solid transparent` + `border-image` + `padding: var(--pad-X)` 세트로 쓴다 (`style.css:141`).
- 새 프레임 요소를 추가하려면: `style.css` 기본값 변수 4개, 요소 규칙, `FRAME_SELECTORS` 항목, `ui_theme.json`의 `frames`, README 문서를 같이 고친다.
- 현재 테마(`ui_theme.json`)에는 `note` 프레임이 정의돼 있지 않아서 쪽지는 기본 카드 모양이다 (`style.css` "쪽지" 주석).

## 픽셀 스케일

- 캔버스: `#game canvas { image-rendering: pixelated }`, Phaser는 `pixelArt: true, roundPixels: true` (`main.ts:119`). 확대는 정수 배율(2-4)만 쓴다 (`CameraController.ts`, 맵/방 줌). 부두만 소수 줌을 허용한다.
- DOM의 이미지/캔버스/프레임 요소에는 `image-rendering: pixelated`를 붙인다 (`img, .framed`, `.panel`, `.shop-item canvas`, `#ctx`, `#toast`, `.note-paper`). 새 `<canvas>` 썸네일이나 `<img>`를 만들면 같은 속성을 준다.
- 프레임 PNG는 `ui_theme.json`의 `scale`(현재 2)배로 확대되어 `--slice-X-px`로 들어간다. 썸네일은 `ctx.imageSmoothingEnabled = false`로 그린다 (`shop.ts:56`).

## 레이아웃: 폰 vs 데스크톱

- 기본은 폰: `.panel`은 화면 아래에서 올라오는 시트 (`left/right: 8px; bottom: 8px; max-height: 70vh; overflow: auto; z-index: 20`).
- 데스크톱 판정은 하나다: `@media (min-width: 900px) and (pointer: fine)` (`style.css:222`)와 `hud.ts isDesktop()`. 이 조건에서 `.panel`은 오른쪽 사이드바(`width: 360px`, 위 56px부터 아래까지)가 되고, `#placebar, #bottombar`는 `right: 384px`로 비켜난다. 모바일 판정은 같은 조건의 반대(`max-width: 899px, pointer: coarse`)다.
- `.overlay`(HUD/바 공통): `position: fixed; display: flex; gap: 8px; padding: 8px; pointer-events: none`, 자식만 `pointer-events: auto`. 안전 영역은 `--safe-top/--safe-bottom`을 쓴다. 상단 `#hud`, 하단 `#bottombar`, 배치 중 `#placebar`, 부두 `#dockbar/#fishbar`, 광산 `#minebar`.
- 접기: `#hud.folded`, `#bottombar.folded` + ▾ 칩. 접힘 상태는 `localStorage`에 기억한다 (`hud.ts initFold`, try/catch).
- 데스크톱 전용 동작은 `isDesktop()` 또는 `matchMedia("(pointer: fine)")`로 가른다: 호버 밝기, 패널 열 때 입력창 포커스 (폰은 키보드가 가려서 하지 않는다, `shop.ts:134`, `note.ts:45`).
- 그리드는 `minmax(0, 1fr)`을 쓴다 (사이드바에서 긴 이름이 넘치지 않게, `style.css:225` 주석).
- 폰의 `#bottombar` 큰 버튼은 `flex: 1 1 0; min-width: 0`으로 같이 줄어든다 (상점·아바타·기록·채팅 네 개가 좁은 폰에 들어가야 한다). 하단 큰 버튼을 하나 더 늘리기 전에 폰 폭(390px)에서 글자가 깨지지 않는지 본다.
- 소프트 키보드: `position: fixed` 시트는 안드로이드에서는 키보드와 같이 올라가지만 iOS는 layout viewport가 안 줄어 입력창이 키보드 밑에 숨는다. 입력창이 아래에 붙은 패널(`panel-chat`)은 열려 있는 동안 `visualViewport`의 `resize`/`scroll`을 듣고 인라인 `bottom`/`max-height`로 시트를 올린다 (`chat.ts fitKeyboard`, 닫을 때 원복). 보내기 버튼은 `pointerdown`에서 `preventDefault()`로 입력창 포커스를 지켜 키보드가 내려가지 않게 한다. 한글 IME는 `keydown`의 `isComposing`이 true인 Enter를 무시한다.

## 패널 구조와 열고 닫기

실제 패널(`panel-shop`, `panel-log`, `panel-board`, `panel-note`, `panel-chat`, `panel-accounts`, `panel-avatar`, `panel-floor`)의 공통 패턴.

**DOM (index.html)**
```html
<div id="panel-x" class="panel hidden">
  <div class="panel-head"><span>제목</span><button class="close" data-close="panel-x">✕</button></div>
  ...본문 컨테이너(id로 지정)...
</div>
```
- 숨김은 `.hidden { display: none !important }` 클래스 토글뿐이다. `hidden` 속성이나 `style.display`는 쓰지 않는다 (예외: `#loading`도 같은 클래스).
- 헤더 제목은 이모지 + 이름 (`📜 기록`, `📋 게시판`) 또는 이름만 (`상점`, `계정`). 섹션 소제목은 `.panel-sub`.
- 버튼 줄은 `.row`(`.row.small`은 작은 버튼), 한 줄 입력은 `.row > input + button`.

**TS (`ui/<name>.ts`)**
- `export function initX(): void`에서 `bus.on(...)`과 `addEventListener`를 연결하고, `main.ts`가 `initHud()` 다음에 모두 호출한다 (`main.ts:101-108`).
- 요소 접근은 `ui/hud.ts`의 `$(id)`(없으면 throw), `show(id, on)`, `togglePanel(id)`, `closeAllPanels()`, `guard(btn, asyncFn)`.
- 연 방식은 두 가지다. 사용자가 버튼으로 연다: `togglePanel("panel-x")`. 씬이나 다른 UI가 연다: `bus.emit("x:open", ...)` -> `bus.on("x:open", open)` (`board:open`, `log:open`, `shop:open`, `item:note`). `togglePanel`은 먼저 다른 패널을 모두 닫으므로 패널은 항상 하나만 열린다. 열린 직후 `hidden`이 아니면 그때 렌더/로드한다 (`log.ts:241`).
- 닫기: `[data-close]` 버튼 (`hud.ts initHud`가 일괄 연결), Esc (입력창 포커스 중이 아닐 때 `closeAllPanels()`), 다른 패널을 열 때, 장면 전환 시 `bus.on("scene:changed")` (`note.ts:66`). `closeAllPanels`는 `panel-enter`가 열려 있으면 "아니오" 응답을 같이 보낸다.
- 열려 있을 때만 다시 그린다: `bus.on("progress:changed", () => { if (isOpen()) render(); })` (`board.ts:79`, `log.ts:264`). 닫힌 패널은 렌더 비용을 쓰지 않는다.
- DOM 생성: 목록 카드는 `document.createElement` + `className` + `textContent`로 만든다. board/log는 로컬 `el(tag, cls, text)` 헬퍼를 각자 갖고 있다 (`board.ts:23`, train은 `train/ui/dom.ts`에 별도). 사용자 입력이나 서버 문자열은 `textContent`로 넣는다. `innerHTML`은 고정 템플릿에만 쓰는 것이 관행이다 (예외: `shop.ts:75`는 아이템 이름을 `insertAdjacentHTML`로 넣는다. 카탈로그 값이라 지금은 안전하지만 `textContent`가 낫다).
- 비동기 저장 버튼은 `disabled`로 이중 클릭을 막고 `try/catch/finally`로 복구하거나 `guard()`를 쓴다 (`note.ts:49`).
- 에러는 항상 `toast(e instanceof ApiError ? msgFor(e.code) : String(e))` 한 줄이다 (`note.ts:60`, `board.ts:165`, `accounts.ts:27` 등 거의 전부).

## 토스트

- `bus.ts`의 `toast(text, ms?)`가 유일한 진입점. 기본 시간은 `min(6000, 1500 + 글자수 * 60)`ms이고, 강조 알림만 `4000`처럼 직접 준다 (`log.ts:268`).
- `#toast`는 하나뿐이다. 새 토스트가 이전 것을 덮어쓴다 (`hud.ts:73`, 타이머 재설정). 큐가 없으니 연달아 띄우지 않는다.
- 위치: 상단 중앙 `top: safe-top + 56px`, `max-width: 90vw`, `z-index: 40`. 프레임은 `toast`.
- 예외: `hud.ts`는 `toast` 함수 대신 `bus.emit("toast", { text })`를 직접 쓴다 (`hud.ts:260-280`). 동작은 같지만 시간 계산이 빠진다. `toast()`를 쓰는 쪽이 지배적이다.
- 글 규칙은 `copy.md`.

## 버튼과 칩

- 기본 `button`은 알약 모양(`border-radius: 999px`), `--chip` 배경. 변형: `.big`(하단 큰 버튼: `--panel` 배경, 그림자), `.primary`(`--primary`), `.danger`, `.close`(투명 ✕). 선택 상태는 `.on`/`.active`/`.deepest`, 비활성은 `:disabled`나 `.disabled`(opacity .4).
- `.chip`은 읽기 전용 표시 또는 작은 버튼(HUD). `<button class="chip">`과 `<div class="chip">` 둘 다 쓴다.
- 눌림: `button:active { transform: scale(0.97) }`. 데스크톱 호버: `filter: brightness(1.15)`.
- 한 화면에서 `primary`는 확정 동작 하나에만 붙인다 (`놓기`, `저장`, `남기기`, `들어가기`). 취소/닫기는 기본 버튼.
- 컨텍스트 메뉴 `#ctx`는 `contextMenu.ts`가 열고 `item:menu` 이벤트로 연결된다. 항목은 `#ctx button`(왼쪽 정렬, 패딩 12px 14px).

## HUD 칩

- `#hud`는 칩 한 줄: 계정(👤), 잔액(💰), 접속 수(🟢), 현재 방(🏠), 동기화(🔄), 소리(🔊), 연결 끊김 경고, 접기(▾). 칩은 `id`로 찾아 `textContent`를 갱신한다 (`hud-balance-val` 등, 값은 `<span id="...-val">`).
- 조건부 칩은 `hidden`으로 토글한다 (`hud-room`, `hud-conn`). `title` 속성에 한국어 설명을 단다.
- 접힌 HUD는 계정 칩, 접기 버튼, 연결 경고만 남긴다 (`style.css:45`).
- 긴 텍스트는 `max-width` + `text-overflow: ellipsis` (`#btn-accounts`).

## 아이콘

이모지 대신 도트 아이콘을 쓴다. 출처 우선순위, 크기 규칙, 이모지별 대체표는 [icons.md](icons.md).

## 열차 추적 페이지 (`/train/`)는 별도 스타일

- `client/train/index.html`은 `<html class="train">`이고 로드 순서가 `style.css` -> `train/style.css` -> `theme.css` -> `train/cyber.css`다. 같은 토큰, 같은 `.panel/.chip/button/.row` 클래스를 공유하고 그 위에 덧쓴다.
- `src/train/cyber.css`는 생성물이다 (`preprocess.py train-ui`, 첫 줄에 "Do not edit"). 색 토큰(`--bg #0b0f1e`, `--primary #37d6e6` 등)과 프레임(`status_button`, `alert`, `activity_box`)을 `html.train:root`로 덮는다. `.ic-*` 아이콘 스프라이트(`media/train/icons.png`)와 `<i class="ic ic-home">`도 여기서 온다.
- `src/train/style.css`(손으로 쓰는 쪽)는 train 전용 컴포넌트: `.bar` 하단 바(접기 포함), 로비 행, 리포트 텍스트, 배너, 라운드 로그.
- 규칙: 사이버 스타일은 train 전용이다. 모든 규칙은 `html.train`/`.train` 아래에 있거나 train 페이지에서만 로드되는 파일에 둔다. 방 게임의 `style.css`/`theme.css`에는 사이버 색, `--frame-bar`, `.ic` 스프라이트를 넣지 않고, 반대로 train 코드는 방 게임 파일을 고치지 않고 덮어쓴다.
- 일관성 메모: train의 `ui/dom.ts`는 방 게임 `ui/hud.ts`와 같은 이름의 `$ / show / el`을 따로 구현한다 (`train/ui/dom.ts`). 패널 열기도 `openPanel(id)`(나머지를 닫음)로 이름만 다르다. 이모지와 `.ic` 아이콘이 섞여 있다 (`train/main.ts:381`은 이모지 사용).

## 알려진 불일치 (지배적 패턴을 따를 것)

- `el()` 헬퍼가 `board.ts`, `log.ts`, `train/ui/dom.ts`에 중복 정의돼 있다. 공용화는 안 됐고 새 UI도 로컬 헬퍼를 두는 편이다.
- 인라인 `style="color:var(--muted)"`가 index.html 일부에 있다 (`panel-shop`, `shop-empty`, `enter-text` margin). 새 코드는 클래스를 쓴다 (`.muted`는 train에만 있고 방 게임 `style.css`에는 없다).
- 하드코딩 색(위 목록)이 테마를 따르지 않는다.
- `hud.ts`의 `bus.emit("toast")` 직접 호출 vs `toast()`.
