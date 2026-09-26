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
In the editor, tick slices in the list (☑ 전체 / ☑ auto = everything visible on the current sheet + search) and press
**이름 일괄 변경**: each `auto_`/`new_` key becomes `[<folder>_]<sheet><original>`, e.g. `auto_interiors_017` → `inte_017`,
a Map sheet `.../Grass.png` → `map_gras_003` (folder omitted when it is `Interior`; sheet = first 4 letters of the file
name; collisions get `_2`, `_3`…). Items using the slice follow the rename. Named slices are left alone.
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

## 에디터 탭 정리

- **시트·슬라이스**: 시트 드롭다운에 `assets/graphic/Interior`·`Map` 아래 모든 PNG가 자동으로 뜬다 (이름 있는 시트 / 팩 전체 / 맵 세 그룹, 위 칸에 이름 일부를 치면 걸러짐).
  맵 그룹 시트에서 만든 슬라이스는 `map_slices.json`으로 간다. 슬라이스에 `scale`(32px 타일은 0.5)과 `배경색 제거`(단색 배경 시트용, "찍기"로 픽셀 클릭)를 줄 수 있다.
  원본이 없는 시트(동결)도 목록에 뜨지만 좌표는 못 바꾼다.
- **아이템**: items.json 전체를 썸네일로 검색·태그·레이어로 거른다. 카드 클릭 → 그 슬라이스로 이동.
  오른쪽 아이템 폼의 **태그**(`ruined`, `fixed`, `stairs` …)와 **쌍(pair)**: 부서진 가구 ↔ 멀쩡한 가구를 양방향으로 잇는다. `ruined` 체크박스는 태그 단축키.
- **낱개**: 정식 팩 `Theme_Sorter_Singles`의 낱개 PNG를 테마별 썸네일로 보고 클릭하면 `file` 슬라이스가 생긴다.
- **캐릭터**: 전과 같음.
- **방·맵 에디터** (`/world`): 아래 참고.

## 방·맵 에디터 (`python tools/preprocess/preprocess.py editor` → 상단 "방·맵 에디터 →")

**방** 탭: `data/rooms/<id>.json`. 방 추가/복제/삭제, 이름, cols/rows/wall_rows/zoom, 벽·바닥 타일(`tile_*` 슬라이스), 막힌 칸, 스폰.
- **시드**: 팔레트에서 아이템을 고르고 "시드 놓기"로 클릭. 게임 시작 시 `$seed` 소유로 미리 놓이고 화면엔 "???"로 보인다. 시드는 방 밖으로 삐져나가거나 서로 겹쳐도 된다(원근·연출용). 단 가구는 바닥 칸(발 위치), 벽지·벽 장식은 벽 칸에 있어야 하고, 소품은 is_surface 가구 위여야 한다 — 어기면 빨간 칸으로 표시되고 게임에서 건너뛴다. `ruined` 태그면 팔 수 있고, `fixed`면 못 건드린다.
- **출구(기믹)**: "출구 그리기"로 사각형을 드래그 → 어느 방(`inn_2f` 등)이나 `map`으로 갈지, 도착 좌표. 아바타가 그 칸에 도착하면 이동. 계단 스프라이트는 같은 자리에 시드로 놓고 `stairs, fixed` 태그.
- 서버는 시작할 때 방마다 **한 번만** 시드를 놓는다 (`room_meta`의 `seeded:<id>`). 시드를 고친 뒤 다시 놓고 싶으면 VM에서 `sqlite3 server/interior.db "DELETE FROM room_meta WHERE k='seeded:inn'"` 후 재시작 (이미 놓인 물건은 그대로 두고 빈 자리에만 추가된다).
- 저장하면 `inn`은 예전 서버가 읽던 `data/room.json`에도 복사된다 (`data/rooms/`가 있으면 서버는 그쪽을 쓴다).

**맵** 탭: `data/map.json`. cols/rows(크기 적용 버튼), ground/deco 두 레이어에 맵 슬라이스를 칠하기(우클릭=지우개), 막힌 칸, 스폰.
- **장소**: 큰 스프라이트(집·표지판)를 고르면 "장소 놓기"로 바뀐다. 클릭해서 놓고 → 방 id(또는 `dock`), 이름, 문 칸("문 칸 찍기"). 아바타가 문 칸에 도착하면 "들어가시겠습니까?".
- 비교용 캐릭터(16×32)가 스폰 위치에 그려진다. 집이 너무 크면 슬라이스 에디터에서 그 집 슬라이스에 `scale` 0.5를 주고 빌드.
- 팔레트는 마지막 빌드의 `gen/map.png` 기준. 슬라이스를 추가했으면 빌드 후 새로고침.
- **데코**(`map.decos[]`): 나무·바위처럼 타일 위에 겹쳐 놓는 오브젝트. 팔레트에서 16px보다 큰 스프라이트를 고르면 "데코 놓기"(집 이름이면 "장소 놓기"). ground/deco 타일 레이어와 무관하게 grass·water 위에 놓을 수 있다.
- **회전·반전**: 장소/데코를 선택하고 `R`(90°씩) / `F`(좌우 반전), 또는 패널 버튼. `rot`(0/90/180/270)·`flip` 필드로 저장. 90/270이면 칸 수 w/h가 바뀐다. 게임 씬은 `setAngle/setFlipX`로 같은 값을 쓰면 된다.
- **문 여러 칸**: 장소의 "문 칸 찍기"를 켜고 클릭/드래그로 칸 추가, 우클릭으로 제거, 버튼을 다시 누르면 끝. `doors: [[x,y], ...]` (예전 `door:{x,y}`는 열 때 자동 변환).
- **집별 스폰**: 장소마다 `spawn:{x,y}` = 그 집에서 나왔을 때 서는 칸(기본은 첫 문 바로 아래, "스폰 찍기"로 변경). 방 출구의 `to:"map"`은 이 값을 쓰므로 출구 쪽 도착 좌표는 비활성.

**부두** 탭: `data/dock.json` → 빌드/저장 시 `client/public/gen/dock.json`. `assets/graphic/Map/Dock/N.png` 이미지 레이어와 슬라이스(맵·실내 아틀라스) 레이어를 겹쳐 놓는다.
- 목록 위가 앞. ↑/↓로 순서, 체크로 표시/숨김, 캔버스 드래그로 픽셀 단위 이동(Shift=16px 스냅), 슬라이스는 scale.
- 게임에서는 `DockScene`이 `gen/dock.json`을 읽어 같은 순서로 그린다(아바타 없음, 왼쪽 위 나가기·낚시 버튼). 지금은 주소 뒤에 `#dock`을 붙여 들어가고, 맵 장소의 `room: "dock"` 연결은 맵 씬과 함께.
- VM에 올릴 것: `client/public/gen/dock.json`, `client/public/gen/dock/*.png`, 그리고 클라를 다시 빌드했으면 `server/static/`.

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
