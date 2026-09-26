# preprocess

Turns the raw packs in `assets/` (gitignored) into clean sheets under `client/public/gen/`.

`assets/graphic/`은 용도별로 세 폴더: `Interior/`(방·가구·캐릭터 팩), `Map/`(바깥 맵 타일, 부두 배경), `GUI/`(프레임·아이콘).
`config.py`의 `SHEETS`(실내)와 `MAP_SHEETS`(맵)가 각 시트 경로를 잡고 있다.

```
python tools/preprocess/preprocess.py scan --sheet interiors   # find pieces → slices.json + contact_interiors.png
python tools/preprocess/preprocess.py build                    # named slices → interiors.png/.json, chars/, map.png/.json, dock/, manifest.json
python tools/preprocess/preprocess.py scaffold                 # add placeholder items.json rows for new keys
```

## 편집기 (좌표 안 찾아도 됨)

```
python tools/preprocess/preprocess.py editor      # = python tools/preprocess/editor.py, 브라우저가 열림
```
시트를 골라 확대해서 보면서 **빈 곳을 드래그하면 새 슬라이스**(16px 격자 스냅), 박스를 클릭·드래그·모서리로 이동/크기 조절, 방향키로 한 칸씩.
오른쪽 패널에서 key·좌표·`parts`(세로 이어붙이기), 잘린 결과 미리보기, 같은 key의 `items.json` 항목(이름·가격·칸수·레이어·is_surface),
방에 놓인 모습(벽지는 폭 슬라이더)까지 보고 **슬라이스 저장 / 아이템 저장 / 빌드** 버튼으로 마무리. 빌드 후 `client/public/gen/`을 VM에 올리면 됨.

Workflow for adding furniture:
1. `scan`, open `contact_interiors.png`, find the red `#NNN` label of the piece you want.
2. In `slices.json` rename `auto_interiors_NNN` to a real key (e.g. `sofa_blue`). Fix x/y/w/h if the scan merged neighbours.
3. `build`, then `scaffold`, then edit the new row in `data/items.json` (name, price, footprint w/h, layer, is_surface).

A slice can also be `"parts": [{sheet,x,y,w,h}, ...]` — rects stacked top-to-bottom into one frame (used for the wallpaper strips whose blocks are separated by transparent lines; every wallpaper is cut to 48px = 3 wall rows).

Only named slices (not `auto_*`) go into the atlas. Keys starting with `tile_` are room tiles, not shop items.
Character strips: 24 frames = 6 per direction in order right, up, left, down. `run` then `idle` are concatenated (48 frames).

## 정식 팩 낱개 가구 (Theme_Sorter_Singles)

`assets/graphic/Interior/moderninteriors-win/1_Interiors/16x16/Theme_Sorter_Singles/<테마>/`에 가구가 한 장씩 PNG로 있다 (탐색기에서 미리보기로 고르면 됨).
`slices.json`에 좌표 대신 파일로 추가:

```json
{"key": "bed_blue", "file": "moderninteriors-win/1_Interiors/16x16/Theme_Sorter_Singles/4_Bedroom_Singles/Bedroom_Singles_12.png"}
```

경로는 `assets/graphic/Interior/` 기준. 그 다음 `build` → `scaffold` → `data/items.json`에서 이름/가격 편집 (footprint w/h는 내가 잡음).

## 동결(freeze): 소스 팩이 사라진 슬라이스

`build`는 슬라이스의 시트/파일이 디스크에 없으면 **직전 아틀라스(`gen/interiors.png`)의 프레임을 그대로 복사**한다.
끝나면 `WARNING: N interior slices copied from the previous atlas ...`로 어떤 시트의 어떤 키가 동결됐는지 찍힌다.
지금은 `Modern tiles_Free` 팩(`interiors`, `room_builder` 시트, 184개)이 그렇다. 동결된 슬라이스는 에디터에서 좌표를 바꿔도 반영되지 않는다.
팩을 다시 `assets/graphic/Interior/Modern tiles_Free/`에 넣으면 다음 빌드부터 원본에서 잘린다.
아틀라스와 직전 아틀라스 둘 다에 없는 키는 예전처럼 빌드가 멈춘다.

캐릭터 레이어는 **줄어들면 빌드가 거부**된다 (`refusing to shrink character layers`). 캐릭터 생성기 폴더가 없는 PC에서 빌드하면
머리 508종이 사라지고 DB에 저장된 아바타 인덱스가 밀리기 때문. 정말 줄이려는 거면 `build --allow-shrink`.

## 맵 · 부두 에셋 (`map_slices.json`, `gen/map.*`, `gen/dock/`)

```
python tools/preprocess/preprocess.py scan --map --sheet houses   # MAP_SHEETS 시트를 map_slices.json으로 스캔
python tools/preprocess/preprocess.py build                        # map_slices.json → gen/map.png + map.json, Map/Dock/N.png → gen/dock/N.png
```
- `map_slices.json`은 `slices.json`과 같은 형식. `file` 경로는 `assets/graphic/` 기준 (예: `GUI/Map Legend Icons/Icons/Exclamation.png`).
- 배경이 단색으로 칠해진 시트(`Houses.png`)는 슬라이스에 `"transparent": [202, 226, 234]`를 주면 그 색이 투명으로 빠진다.
- 키에 `sheet`라는 단어는 쓰지 말 것 (서버 테스트가 `/api/catalog` 출력에 그 문자열이 없는지 검사한다).
- manifest에 `map: {atlas, keys}`, `dock: {layers, w, h}`가 추가된다. 부두 레이어는 0(뒤) → 8(앞) 순서, 전부 같은 크기여야 한다.

## 캐릭터 레이어

`config.py`의 `CHAR_LAYERS`가 Character_Generator 폴더(Bodies/Eyes/Outfits/Hairstyles/Accessories, 16x16)를 자동으로 읽는다.
시트 896×656에서 2번째 줄(idle)·3번째 줄(run)만 잘라 `gen/chars/<layer>/<n>.png`(48프레임)로 만든다.
`Hairstyle_SS_CC` 식 파일명의 SS가 스타일, CC가 색 → manifest의 `groups`로 묶여 에디터에서 "스타일 / 색" 두 줄이 된다.
머리·악세서리는 index 0 = 없음.

## media (BGM · 폰트)

```
python tools/preprocess/preprocess.py media
```
`assets/BGM/day|night/*.mp3` → `client/public/media/bgm/day|night/NN-이름.mp3` + `bgm.json`, `assets/fonts/*.ttf` → `media/fonts/stardust*.ttf`.
곡을 바꾸면 다시 실행. mp3/ttf는 gitignore라 VM에는 rsync.

## UI 스킨 바꾸기 (`data/ui_theme.json`)

```
python tools/preprocess/preprocess.py ui      # → client/public/media/theme.css + media/ui/*.png
```

1. 프레임 PNG를 구한다. 예: `assets/graphic/GUI/Pocket GUI/DIY_16x16.png`를 Aseprite/그림판으로 열어 원하는 박스의 **x, y, w, h**와 테두리 두께(**slice**, 모서리가 늘어나지 않는 픽셀 수)를 적는다.
   직접 잘라 저장했으면 `assets/ui/<이름>.png`로 두고 `file`로 지정해도 된다.
2. `data/ui_theme.json`의 `frames`에 넣는다. 쓸 수 있는 이름: `panel`, `button`, `button_primary`, `chip`, `input`, `ctx`(길게 누르면 뜨는 메뉴), `toast`.
   ```json
   "frames": {
     "panel":  {"sheet": "graphic/GUI/Pocket GUI/DIY_16x16.png", "x": 0, "y": 0, "w": 48, "h": 48, "slice": 8},
     "button": {"file": "ui/button.png", "slice": 6, "pad": 8}
   }
   ```
   `pad` = 안쪽 여백(px, 기본 slice와 같음). `scale` = 화면 배율(2면 원본 1px이 2px). `colors`로 배경/글자/강조색, `font.size`로 글자 크기.
   폰트는 `font.body` / `font.bold`에 `media/fonts/`의 파일 이름(확장자 없이): `stardust`, `stardust-bold`, `stardust-s` 등.
3. `ui` 실행 → 브라우저 새로고침. 프레임을 지우면 원래 둥근 스타일로 돌아간다.
   프레임이 정의된 요소는 배경색·둥근 모서리가 꺼지고 PNG가 9-slice로 늘어난다 (`border-image`).

## 머리 색 추가 (`data/hair_palette.png`)

팩의 `Hairstyles_palette.png`를 복사한 파일. 가로 5px짜리 세로 열 하나가 색 하나이고, 위 3줄 = 밝은색, 가운데 3줄 = 중간, 아래 3줄 = 어두운색.
앞의 8열(7색 + 윤곽선)은 팩 원본이라 건드리지 말고, **오른쪽에 5px 열을 더 그리면** 그 색이 모든 헤어스타일에 추가된다 (예시로 분홍·민트 두 열이 들어있음).
`build` 실행 → 에디터의 "머리 색"이 늘어남. 열을 지우면 색도 사라지니 이미 저장된 아바타 인덱스가 밀릴 수 있음 (뒤에만 붙이는 게 안전).

## 글자 크기 · 이름표 폰트 · 미리보기 크기 (`data/ui_theme.json`)

```json
"font": {"body": "stardust", "bold": "stardust-bold", "size": 16,
         "sizes": {"small": 13, "button": 16, "big": 18, "title": 18, "preview": 160}},
"label": {"font": "", "size": 16, "color": "#ffffff", "stroke": "#000000", "scale": 0.5}
```
- `size` = 기본 글자(px). `sizes.small` = 상점 아이템 이름/가격·안내문, `button` = 일반 버튼, `big` = 하단 상점/아바타 버튼, `title` = 패널 제목, `preview` = 아바타 미리보기 폭(px, 높이는 4:3 자동).
- `label` = 아바타 머리 위 이름표. `font`는 `media/fonts/`의 파일 이름(확장자 없이, 예 `stardust-s-bold`), 비우면 본문 폰트. 새 폰트를 쓰려면 ttf를 `assets/fonts/`에 넣고 `media` 실행 → 파일명이 `media/fonts/`에 아스키로 복사되니 그 이름을 적기. `size`×`scale`이 실제 게임 픽셀 높이 (16×0.5 = 8px, 화면 zoom 2배라 16px로 보임). 픽셀 폰트는 제작 크기(보통 16)로 두고 scale로 조절하는 게 깨끗함.
- 바꾼 뒤 `python tools/preprocess/preprocess.py ui` → 새로고침. 서버 재시작 불필요.

## 머리/옷/악세서리 직접 그려서 추가하기

게임은 **16x16 폴더**(캔버스 896×656, 프레임 16×32)만 쓴다. 32x32/48x48은 무시.
참고 파일은 `assets/custom/_reference/`에 모아뒀다 (팩에서 복사):
- `Hairstyle_01_01.png`, `Outfit_01_01.png`, `Accessory_04_Snapback_01.png`, `Body_01.png`, `Eyes_01.png` — 레이어별 예시
- `Spritesheet_animations_GUIDE.png` — 어느 줄이 무슨 애니인지
- `Character_template_16x16.png` — 몸 템플릿
- `blank_sheet_rows_marked.png` — 빈 시트. 빨간 격자 = 게임이 실제로 쓰는 부분 (2번째 줄 idle, 3번째 줄 run, 각 24프레임 = 오른쪽/위/왼쪽/아래 × 6프레임). **이 두 줄만 그리면 됨.** 나머지 줄은 비워둬도 됨.

절차:
1. 예시 파일을 Aseprite 등으로 열어 위에 덧그리거나, 빈 시트에 그린다 (캔버스 크기 896×656 유지, 투명 배경).
2. 저장 위치와 이름: `assets/custom/<폴더>/<이름>.png`
   - 머리: `assets/custom/Hairstyles/Hairstyle_30_01.png` (30 = 팩에 없는 새 스타일 번호, 01 = 색 번호. 같은 스타일의 다른 색은 `_02`, `_03`…)
   - 옷: `assets/custom/Outfits/Outfit_34_01.png`
   - 악세: `assets/custom/Accessories/Accessory_20_Name_01.png`
   - 몸/눈: `assets/custom/Bodies/Body_10.png`, `assets/custom/Eyes/Eyes_08.png`
3. `python tools/preprocess/preprocess.py build` → 에디터에 자동으로 나타남.

머리는 색 01을 팔레트의 세 가지 색(밝음 204,150,89 / 중간 179,123,63 / 어둠 171,103,54)으로만 칠하면 `data/hair_palette.png`의 추가 색들이 자동으로 적용된다. 다른 색을 쓰면 그 색 그대로 한 가지만 나옴.
