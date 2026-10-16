# 아이콘 규칙 (이모지 대체)

2026-10-16 조사·적용. 룸 게임 UI(DOM)의 이모지는 모두 바꿨다. 남은 것은 열차 페이지(아래 '열차')와 코드 주석.

## 왜 바꾸나

- 이모지는 OS마다 그림이 다르다(윈도우 / iOS / 안드로이드). 도트 화면 위에서 매끈한 벡터 그림이 혼자 튄다.
- Lucide·Material 같은 선 아이콘도 같은 이유로 쓰지 않는다. 이 게임의 아이콘은 **도트, 정수 배율**이어야 한다.
- 현재 클라이언트에 이모지 166개(💰21 ☕14 ✓8 ✕7 📜6 📋6 📝6 🎣5 🔊4 🐱4 🐶4 …). 가장 많은 곳: `train/report.ts` 32, `index.html` 30, `ui/log.ts` 22, `ui/board.ts` 15.

## 원칙

1. **출처 우선순위**: ① 게임에 이미 있는 스프라이트(가구 아이템, 고양이, 곡괭이 프레임, `icon_lock`) → ② `assets/graphic/GUI` 의 라이선스 팩 → ③ 그래도 없으면 MIT 도트 아이콘 세트(예: pixelarticons) 또는 아이콘 없이 글자만.
2. **크기**: 인라인/칩 아이콘은 16px 원본을 ×1 또는 ×2. 큰 버튼만 32px 원본 허용. 비정수 배율 금지, `image-rendering: pixelated`.
3. **장식용 이모지는 아이콘으로 바꾸지 말고 지운다.** 아이콘은 의미를 전달할 때만 쓴다(돈, 잠김, 완료 등). 패널 제목의 📜·📋 처럼 글자가 이미 의미를 말하면 아이콘 없이 간다.
4. 코드에서는 이름으로만 부른다: DOM은 `icon("coin")`, Phaser는 같은 이름의 텍스처 키. 이모지 문자를 문자열에 직접 쓰지 않는다.
5. 룸 게임은 따뜻한 베이지/브라운 톤(Sprout Lands, Cute Fantasy), 열차(`/train/`)는 cyberpunk GUI 톤. 섞지 않는다.

## 쓸 수 있는 시트

경로는 `assets/graphic/` 기준. 좌표는 (열, 행), 셀 크기 기준.

| 시트 | 셀 | 내용 |
|---|---|---|
| `GUI/Sprout Lands - UI Pack - Basic pack/Sprite sheets/Icons/All Icons.png` | 16 | 18종 × 3색. 흰 0–5열·베이지 6–11열은 행마다 같은 순서, 갈색 12–17열은 순서가 3칸 밀려 있음(0행: 톱니·?·별·게임패드·말풍선·해골, 1행: 순위·트로피·왕관·!·$·카트, 2행: 체크·X·금지·+·−·집) |
| `…/Icons/special icons/Special Icons.png` | 16 | 별(노랑/반/갈색), 하트(분홍/반/보라), 금화. 행마다 테두리 스타일 다름(0행 없음, 1행 흰, 2행 검정, 3행 흰+그림자) |
| `GUI/Sprout Lands …/emojis-free/Emoji_Spritesheet_Free.png` | 32 | 표정, 체크/X/!/?/Zz, 음표, 금화, 하트, 별, 엄지, 식물, 곡괭이, 물뿌리개, 날씨 |
| `Map/Farm/Cute_Fantasy/Icons/Outline/Tool_Icons_Outline.png` | 16 | 활·삽·곡괭이·도끼·검·괭이·물뿌리개·낚싯대·장갑·횃불 |
| `Map/fishing-and-gathering-pixel-art-rpg-icons/PNG_n_Tiled/Icons.png` | 32 | 물고기, 낚싯대, 바늘, 조개, 광물, 버섯 |
| `GUI/cyberpunk GUI/icon.png` | ~32 (격자 어긋남, 자를 때 확인) | 파란 UI 아이콘: 돋보기, 신호 막대, 스피커, 메일, X, ?, !, 톱니, 휴지통, 재생/정지 — **열차 전용** |
| `GUI/UI assets pack 2/UI books & more.png` | 16 (아이콘 묶음은 x 464, y 176부터) | 책·펼친 책·공책·편지·편지함·느낌표 말풍선·지도 핀·해골·모루·화살 하트·열쇠 구멍·자물쇠, 휘어진 화살표, 체크/X. 행마다 테두리(없음 / 흰 / 금색) |
| `GUI/Sprout Lands …/Icons/special icons/Small Happines-Sadness icons.png` | 16 | 표정 6종(웃음 → 해골). 1행은 흰 테두리 |
| `GUI/Map Legend Icons/Icons/*.png` | 16×24 | 지도 핀 모양 — UI 아이콘으로는 부적합, 쓰지 않음 |

## 매핑표 (룸 게임) — 적용됨

이름은 `data/ui_icons.json` 의 키. 좌표는 그 파일에 있다.

| 이모지 | 위치 | 지금 |
|---|---|---|
| 💰 | 돈 (HUD, 토스트, 상점, 기록, 게시판, 배치 라벨) | `coin` (Special Icons 금화) |
| ☕ | 안락도 (HUD 칩, 기록) | `heart` (Special Icons 하트) |
| ✓ | 완료 | `check` (All Icons 갈색) |
| ✕ | 패널 닫기 | `close` (All Icons 갈색 X) |
| 🎉 | 복구 단계 완료 | `star` |
| 🏠 | 방 칩 | `home` |
| 🛋️ 상점 | 큰 버튼 | `cart` |
| 🧍 아바타, 👤 계정 | 큰 버튼, 계정 칩 | `me` (Small Happiness 웃는 얼굴) — 아바타 얼굴 렌더는 나중 후보 |
| 📜 기록 | 큰 버튼 | `book` (books 펼친 책). 패널 제목은 글자만 |
| 🎣 | 낚시 버튼 | `rod` (Cute Fantasy 낚싯대) |
| ⛏ | 채광 버튼 | 지움 — 버튼에 이미 곡괭이 프레임(`#mine-pick`)이 있음. `pickaxe` 아이콘은 준비만 |
| 🐱 | 고양이 호감도 (게시판, 기록) | `cat` (`gen/cat` 꼬리 없는 프레임의 얼굴) |
| 🐶 | 개 손님 | 게시판 카드: `dog` 태그 아이템 썸네일(`itemThumb`). 문구 속 🐶 는 지움 |
| 📦 | 예약 카드 자리 | 빈 칸 → 아이템 썸네일 |
| 📝 | 쪽지 메뉴 | `letter`. 예약 문구 속 📝 는 지움 |
| 🧹 | 부서진 물건 수 (HUD 칩) | `repair` (books 모루) |
| 🔌 | 연결 끊김 | `offline` (All Icons 갈색 금지) |
| 🔄 | 시트 동기화 | `sync` (books 휘어진 화살표) |
| 🔊 / 🔇 | 소리 칩 | 글자 "소리" / "소리 꺼짐" (열차 페이지와 같음). 줄여도 알아볼 스피커 그림이 없었음 |
| 🟢 | 접속 인원 | CSS `.dot` (`--ok`) |
| ✓ ✗ | 접속 기록(`<pre>`) | 글자 "성공" / "실패" |
| 🎲 🚶 🛏️ 🏚️ 📋 📌 | 랜덤 버튼, 여기로 가기, 패널 소제목·제목 | 지움, 글자만 (장식) |

`quest`(느낌표 말풍선)·`lock`(자물쇠)·`notebook`·`pickaxe` 는 아직 안 쓰지만 후보로 쓸 만하다(books 시트 x 592/688/544, y 240; Cute Fantasy x 32). 쓸 때 `ui_icons.json` 에 넣는다.

시도했다가 뺀 것: 개(`pet_bed_fa` ÷3), 거울(÷2), Emoji 시트 음표(32px ÷2) — 정수로 줄여도 뭉개져서 알아보기 어려웠다.

## 열차 (`/train/`)

열차는 cyber 톤이라 룸 게임 아이콘을 쓰지 않는다. cyberpunk `icon.png` 후보: 🔍 → 돋보기, 📶 → 신호 막대, 📢 → 스피커, ⚠ → !, 🛠 → 톱니. ⛔(잠긴 문)·☕(증기)·💥·👁·🕶·🤖 는 대응 그림이 없어 별도 제작 또는 글자 태그(`[잠김]`)가 필요하다. 보고서 줄머리 이모지(`train/report.ts`)는 대부분 장식이라 지우는 쪽이 우선.

## 구현 (적용됨)

- 출처 목록: `data/ui_icons.json` (이름 → `sheet` + x, y [+ w, h], `gen` + x, y, w, h(`client/public/gen` 기준), 또는 gen 아틀라스 `key` [+ 정수 `down`]). 칸은 16px, 투명 여백을 깎아 가운데 정렬, 칸보다 크면 빌드 에러.
- 빌드: `python tools/preprocess/preprocess.py ui` → `media/ui/icons.png` + `theme.css` 끝의 `.icon` / `.icon-<name>` (`tools/preprocess/ui_icons.py`). 테마 `scale`(2)로 그려서 16px 칸 = 32px, 음수 margin으로 글줄 높이는 그대로. `.icon.x2`는 그 두 배(큰 버튼).
- 클라이언트: `client/src/ui/icons.ts`
  - `icon("coin")` → `<i class="icon icon-coin">`
  - 문구 안의 `{coin}` 토큰: `setRich(el, text)` / `richEl(tag, cls, text)`. 토큰만 아이콘이 되고 나머지는 텍스트 노드(innerHTML 아님).
  - 토스트, 배치 라벨, 낚시 상태, 획득 알림, 기록, 게시판, 상점 가격, HUD 방 칩이 이미 `setRich`를 거친다. 새 문구에 `{coin}`을 쓰려면 그 문구가 들어가는 곳이 `setRich`/`richEl`인지 확인.
  - `confirm()` 같은 네이티브 대화상자는 아이콘을 못 그린다 → 숫자만 (`(+12)`).
- 정적 HTML은 `<i class="icon icon-close"></i>` 직접.
- 아이콘 추가 순서: `ui_icons.json`에 한 줄 → `preprocess.py ui` → 코드에서 `{name}`. 열차 페이지는 `.ic-*`(train-ui, cyber)라 `.icon-*`와 섞지 않는다.
- 폰(`max-width: 899px` 또는 터치)에서는 아이콘이 있는 큰 버튼이 아이콘 위·글자 아래로 쌓인다(`style.css`).
- 남은 것: 열차 페이지, Phaser 텍스트 안의 이모지(열차 `Fx.ts` 등)는 텍스트 옆 이미지 오브젝트로 따로.
