# 아이콘 규칙 (이모지 대체)

2026-10-16 조사. 파이프라인과 1순위(💰 ✕ ✓ ☕ 🎉)는 적용됨, 나머지는 아래 표대로 차례로 바꾼다.

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
| `GUI/Map Legend Icons/Icons/*.png` | 16×24 | 지도 핀 모양 — UI 아이콘으로는 부적합, 쓰지 않음 |

## 매핑표 (룸 게임)

| 이모지 | 의미 / 위치 | 대체 | 비고 |
|---|---|---|---|
| 💰 | 돈 (HUD, 토스트, 상점, 기록) | Special Icons 금화 (6,1) | 가장 많이 씀, 1순위 |
| ☕ | 안락도 (HUD 칩, 기록) | Special Icons 하트 (3,1) | 열차의 ☕(증기)와 다른 뜻 |
| ✓ / ✗ | 완료, 성공/실패 | All Icons 갈색 체크 (12,2) / X (13,2) | |
| ✕ | 패널 닫기 | All Icons 갈색 X (13,2) | `index.html` 패널 헤드 7곳 |
| 🎉 | 복구 단계 완료 | Special Icons 별 (0,1) | |
| 🏠 | 방 칩 | All Icons 갈색 집 (17,2) | |
| 🛋️ 상점 | 큰 버튼 | All Icons 갈색 카트 (17,1) | |
| 🎣 | 낚시 버튼, 낚시 토스트 | fishing-and-gathering 낚싯대 (9,2) 또는 Cute Fantasy (7,0) | |
| ⛏ | 채광 | 이미 `pickaxe_1..n.png` 있음 → 1프레임 재사용 | |
| 🐱 | 고양이 호감도 | `gen/cat/<variant>.png` 0프레임 | 게임 내 스프라이트 |
| 🐶 | 개 손님 | `pet_bed_fa` 아이템 스프라이트 | 게임 내 스프라이트 |
| 🛏️ | 손님 섹션 | `bed_pixel_red_single` 아이템 스프라이트 | 섹션 제목이라 지워도 됨 |
| 📋 | 게시판 | `med_018` 스프라이트 | 패널 제목은 글자만 |
| 📝 | 쪽지, 예약 | `notepad_td` 스프라이트 | |
| 📌 | 의뢰 | All Icons 갈색 ! (15,1) | |
| 🔒 | 잠긴 장소 | 지도의 `icon_lock` 슬라이스 재사용 | |
| 🔌 | 연결 끊김 | All Icons 갈색 금지 (14,2) | |
| 📜 기록 | 버튼, 패널 제목 | **빈칸** — `GUI/UI assets pack 2/UI books & more.png` 확인 필요 | |
| 🔊 / 🔇 | 소리 | Emoji 시트 음표 (0,8) / 같은 그림 + 흐리게 | 끔 표시는 투명도로 |
| 🔄 | 시트 동기화 | **빈칸** | pixelarticons 등에서 |
| 👤 | 계정 | 내 아바타 얼굴(캐릭터 레이어 렌더) | |
| 🧍 아바타 | 큰 버튼 | 내 아바타 얼굴 | |
| 🎲 | 아바타 랜덤 | **빈칸** — 글자만("랜덤") | |
| 🧹 | 부서진 물건 수 | **빈칸** | 부서진 아이템 스프라이트 하나 고르기 |
| 🟢 | 접속 인원 | 아이콘 없이 CSS 점(`--primary`) | |
| 🚶 | 여기로 가기 | 지움, 글자만 | 장식 |
| 🏚️ | 복구 섹션 | 지움, 글자만 | 장식 |

(Emoji 시트 좌표는 32px 셀 기준)

## 열차 (`/train/`)

열차는 cyber 톤이라 룸 게임 아이콘을 쓰지 않는다. cyberpunk `icon.png` 후보: 🔍 → 돋보기, 📶 → 신호 막대, 📢 → 스피커, ⚠ → !, 🛠 → 톱니. ⛔(잠긴 문)·☕(증기)·💥·👁·🕶·🤖 는 대응 그림이 없어 별도 제작 또는 글자 태그(`[잠김]`)가 필요하다. 보고서 줄머리 이모지(`train/report.ts`)는 대부분 장식이라 지우는 쪽이 우선.

## 구현 (적용됨)

- 출처 목록: `data/ui_icons.json` (이름 → `sheet` + x, y [+ w, h] 또는 gen 아틀라스 `key` [+ 정수 `down`]). 칸은 16px, 투명 여백을 깎아 가운데 정렬, 칸보다 크면 빌드 에러.
- 빌드: `python tools/preprocess/preprocess.py ui` → `media/ui/icons.png` + `theme.css` 끝의 `.icon` / `.icon-<name>` (`tools/preprocess/ui_icons.py`). 테마 `scale`(2)로 그려서 16px 칸 = 32px, 음수 margin으로 글줄 높이는 그대로. `.icon.x2`는 그 두 배(큰 버튼).
- 클라이언트: `client/src/ui/icons.ts`
  - `icon("coin")` → `<i class="icon icon-coin">`
  - 문구 안의 `{coin}` 토큰: `setRich(el, text)` / `richEl(tag, cls, text)`. 토큰만 아이콘이 되고 나머지는 텍스트 노드(innerHTML 아님).
  - 토스트, 배치 라벨, 낚시 상태, 획득 알림, 기록, 게시판, 상점 가격, HUD 방 칩이 이미 `setRich`를 거친다. 새 문구에 `{coin}`을 쓰려면 그 문구가 들어가는 곳이 `setRich`/`richEl`인지 확인.
  - `confirm()` 같은 네이티브 대화상자는 아이콘을 못 그린다 → 숫자만 (`(+12)`).
- 정적 HTML은 `<i class="icon icon-close"></i>` 직접.
- 아이콘 추가 순서: `ui_icons.json`에 한 줄 → `preprocess.py ui` → 코드에서 `{name}`. 열차 페이지는 `.ic-*`(train-ui, cyber)라 `.icon-*`와 섞지 않는다.
- 남은 것: 매핑표의 나머지 이모지, Phaser 텍스트 안의 이모지(열차 `Fx.ts` 등)는 텍스트 옆 이미지 오브젝트로 따로.
