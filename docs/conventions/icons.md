# 아이콘 규칙 (이모지 대체)

2026-10-16 조사. 아직 적용 전 — 이 문서는 무엇을 무엇으로 바꿀지의 기준표다.

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

## 구현 메모 (적용 시)

- `preprocess.py ui`(또는 새 `icons` 명령)가 `data/ui_icons.json`(이름 → 시트, x, y, w, h)을 읽어 `media/ui/icons.png` 아틀라스 + CSS(`.icon-coin` 등)를 생성. 게임 내 스프라이트 출처는 manifest 키로 지정.
- 토스트/기록 문구에 아이콘이 들어가므로 `textContent` 대신 안전한 렌더러가 필요: 문자열 토큰(`{coin}`)만 `<i class="icon icon-coin">`로 바꾸고 나머지는 텍스트 노드로 넣는다(innerHTML 금지).
- Phaser 쪽(`Placement.ts` 가격 라벨, 열차 `Fx.ts`)은 텍스트 옆에 이미지 오브젝트를 둔다.
- 1순위: 💰 ✕ ✓ ☕ 🔒 (전체 이모지의 절반 가량, 화면에 늘 보임).
