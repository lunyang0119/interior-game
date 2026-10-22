# 작업 절차 (workflow)

지금 실제로 돌아가는 절차를 순서대로 적었다. 긴 설명은 복사하지 않고 링크한다.
기본 문서: [`CLAUDE.md`](../../CLAUDE.md) (구조), [`README.md`](../../README.md) (배포/운영), [`tools/preprocess/README.md`](../../tools/preprocess/README.md) (에셋 파이프라인, 에디터, 데이터 형식).

## 공통 주의

- 브라우저 에디터(`preprocess.py editor`)가 떠 있으면 저장 때 메모리의 내용이 `data/items.json` 등을 덮어쓴다. 디스크에서 직접 고친 내용이 사라질 수 있다. 스크립트로 고칠 때는 에디터를 닫거나, 고친 뒤 에디터 탭을 새로고침하라고 사용자에게 알린다. 스크립트는 다시 돌려도 안전하게(idempotent) 만든다.
- `assets/`, `client/public/gen/*.png`, `gen/chars/`, `gen/dock/`, media 바이너리, `server/static/`은 gitignore다. PC에서 만들고 VM에 올린다.
- 슬라이스 키에 `sheet`라는 단어를 쓰지 않는다 (서버 테스트가 `/api/catalog`에서 검사한다).
- 커밋은 사용자가 요청할 때만 한다.

## 가구 추가

1. `python tools/preprocess/preprocess.py scan --sheet interiors`로 `contact_interiors.png`에서 조각 번호(`#NNN`)를 찾는다. 또는 에디터에서 시트를 열고 빈 곳을 드래그해 새 슬라이스를 만든다.
2. `tools/preprocess/slices.json`의 `auto_interiors_NNN`을 의미 있는 키로 바꾼다 (`sofa_blue`). 이름이 `auto_*`인 것은 아틀라스에 들어가지 않는다. `tile_` 접두사는 방 타일이고 상점 아이템이 아니다.
3. `python tools/preprocess/preprocess.py build` -> `client/public/gen/`(아틀라스, `manifest.json`). 캐릭터 레이어가 줄어들면 `build`가 거부한다 (`--allow-shrink`는 저장된 아바타가 밀릴 때만 의도적으로).
4. `python tools/preprocess/preprocess.py scaffold`로 새 키의 임시 행을 `data/items.json`에 추가한다.
5. `data/items.json`의 새 행을 고친다: 이름, 가격, 칸수 `w/h`, `layer`, `is_surface`, `tags`. 태그 목록과 설명은 `tools/preprocess/editor.py KNOWN_TAGS`가 유일한 원본이다. `set`은 `build`가 소스에서 만들어 매니페스트에 쓰므로 `items.json`에 쓰지 않는다.
6. 서버 재시작 시 `catalog.py`가 검증한다. 틀리면 시작 시점에 pydantic 에러가 난다. `cd server && pytest`로 확인.
7. 에디터 "아이템" 탭에서 해도 된다 (슬라이스 저장 / 아이템 저장 / 빌드 버튼). 이 경우 에디터가 `items.json`을 쓰는 쪽이니 위 "공통 주의"를 지킨다.

배포 대상: `client/public/gen/*` (재시작 필요: `gen/manifest.json`을 서버가 읽는다), `data/items.json`.

## 방 추가/수정과 재시드

1. 에디터의 "방·맵 에디터" -> 방 탭에서 `data/rooms/<id>.json`을 만든다 (크기, 타일, 막힌 칸, 스폰, 시드, 출구, 구역, 효과). 형식은 `tools/preprocess/README.md` "방·맵 에디터". `inn`은 필수다.
2. 복구 단계(`restore`), `fx.when`, `kind: "mine"`, 열차 칸(`data/train_interiors.json`)은 에디터 UI가 일부만 있어 JSON을 직접 쓰기도 한다. 검증은 서버 시작/`catalog.load`에서 한다.
3. 맵에서 문으로 연결하려면 맵 탭에서 장소를 찍는다 (`data/map.json`).
4. 서버는 방마다 시드를 한 번만 놓는다 (`room_meta`의 `seeded:<id>`, `seed_hash:<id>`). 시드를 고쳤으면 VM의 DB에서 두 행을 지우고 재시작해야 반영된다:
   ```bash
   sudo systemctl stop interior
   sqlite3 <DB_PATH> "DELETE FROM room_meta WHERE k IN ('seeded:<id>','seed_hash:<id>');"
   sudo systemctl start interior
   ```
   로그에 `seeded room <id>: N items`가 나오면 된 것이다. 복구 단계를 처음부터 다시 하려면 `stage:<id>`, `stage_ts:<id>`를 지운다 (README "맵 바꿀 때").
5. 로컬 개발에서는 `server/interior.db`에서 같은 행을 지운다.
6. 잠긴 방을 디버그하려면 `DEBUG_PLAYERS` 계정으로 들어간다 (CLAUDE.md "Restoration").

## UI 패널 추가

패턴 전체는 [`ui.md`](ui.md)의 "패널 구조와 열고 닫기". 순서만 적는다.

1. `client/index.html`에 `<div id="panel-x" class="panel hidden">` + `.panel-head`(`data-close="panel-x"` 버튼) + 본문 컨테이너를 추가한다.
2. 필요한 스타일을 `client/src/style.css`에 `#panel-x ...` 형태로 추가한다. 카드는 기존 `var(--card)` 카드 모양을 복사한다. 색은 변수만 쓴다.
3. 이벤트가 필요하면 `client/src/bus.ts`의 `Events`에 타입을 추가한다 (`"x:open": void`).
4. `client/src/ui/x.ts`에 `export function initX()`를 만든다. `bus.on("x:open", open)`, `togglePanel("panel-x")`, 열린 상태에서만 재렌더, 에러는 `toast(msgFor(code))`.
5. `client/src/main.ts`의 `initHud(); initShop(); ...` 목록에 `initX()`를 추가한다. 하단 버튼이 필요하면 `#bottombar`에 `class="big"` 버튼을 추가하고 `initX`에서 클릭을 연결한다.
6. 글은 [`copy.md`](copy.md). 테마 프레임이 필요한 새 요소를 만들면 `ui.md` "9-slice 프레임"의 목록을 모두 고친다.
7. 확인: `cd client && npm run build` (타입 체크 포함), 폰 폭과 데스크톱 폭(>= 900px, 마우스) 둘 다 본다.
8. 열차 페이지(`client/train/index.html`)의 UI는 `src/train/ui/`에서 따로 한다. 방 게임 `ui/`와 섞지 않는다.

## DB 마이그레이션 추가

1. `server/migrations/`에 다음 번호로 `NNN_name.sql`을 만든다 (현재 마지막 `016_train.sql` -> `017_...`). 파일명 앞 숫자가 `PRAGMA user_version`이 된다 (`server/app/db.py migrate`).
2. SQL만 쓴다. 러너가 `BEGIN; ... PRAGMA user_version = N; COMMIT;`로 감싸므로 `BEGIN/COMMIT`을 넣지 않는다. 첫 줄 주석으로 목적을 한두 줄 적는 것이 관행이다 (`016_train.sql`).
3. 이미 적용된 파일은 고치지 않는다. 바꾸려면 새 번호로 `ALTER`/새 테이블.
4. 서버는 시작할 때 자동 적용한다. 배포 시 `server/migrations`가 `sync.sh`에 포함되고, 서비스 재시작이 필요하다.
5. 테스트는 `server/tests/conftest.py`의 임시 DB가 마이그레이션을 처음부터 적용한다. `pytest`로 확인.
6. 스키마를 바꾸면 `CLAUDE.md`의 해당 절(숫자, 테이블 이름)을 사용자에게 알려 같이 고치게 한다.

## 배치 규칙 변경

서버 `server/app/placement.py`가 원본이고 `client/src/room/rules.ts`는 고스트 색용 미러다. 항상 같이 고친다.

1. `placement.py` 수정 (순수 함수, DB 없음).
2. `rules.ts`에 같은 조건을 반영한다 (층, 충돌 레이어, `surface_item`, `walk:false`, `partition_face`).
3. `server/tests/test_placement.py`에 케이스를 추가하고 `pytest tests/test_placement.py -k 이름`.
4. 시드는 `relaxed=True`로 검증을 완화한다 (`seed.py`). 규칙을 조이면 기존 시드/저장된 아이템이 깨지는지 `reconcile.py`와 `test_rooms.py`를 본다.
5. 새 에러 코드를 만들면 `client/src/api.ts MESSAGES`에 문장을 넣는다 ([`copy.md`](copy.md)).

## 테스트와 빌드

```bash
# server (server/, venv server/.venv)
pip install -e ".[dev]"
pytest                                   # 전체
pytest tests/test_placement.py -k name   # 하나

# client (client/)
npm run dev          # /api, /ws를 localhost:8000으로 프록시
npm run build        # tsc --noEmit && vite build -> ../server/static

# 파이프라인 (repo root)
pytest tools/preprocess/tests
python tools/preprocess/preprocess.py build | ui | media | train-ui
```

- 로컬 서버: `uvicorn app.main:app --reload --port 8000` (`SHEET_URL`이 비면 `data/fake_sheet.json`).
- 클라이언트 변경은 `npm run build`가 타입 체크를 겸한다. 서버 변경은 `pytest`.
- `data/ui_theme.json`을 바꿨으면 `preprocess.py ui` 후 새로고침. 서버 재시작은 필요 없지만 VM에서는 `asset_version` 때문에 재시작한다 (아래).

## 배포 (VM)

VM에서 `git pull`을 하지 않는다. `deploy/push.sh`도 쓰지 않는다. 자세한 사용법과 ssh 설정은 README "배포".

```bash
./deploy/pull.sh ubuntu@<host>            # 먼저: VM 에디터(edit.<host>)로 고친 data/ 를 가져와 커밋
./deploy/sync.sh ubuntu@<host>            # 클라 빌드 -> server/app, migrations, data, gen, static, tools/preprocess -> 재시작
./deploy/sync.sh ubuntu@<host> --media    # media(BGM, 폰트, 효과음)도 바뀌었을 때
./deploy/sync.sh ubuntu@<host> --no-build --no-restart
```

`data/`는 VM 에디터에서도 바뀔 수 있다. `sync.sh`는 VM 쪽이 마지막 sync/pull 이후 바뀌었으면 덮어쓸지 묻는다(`--force`로 생략). 보고할 때 "VM에서 data를 고친 적이 있으면 pull 먼저"라고 한 줄 적는다. 서버 기동 검증을 바꿀 때는 `lifespan`이 아니라 `app.main.check_data()`에 넣는다(VM 에디터의 "게임에 반영"이 같은 함수를 돌린다).

사용자가 직접 올릴지 판단할 수 있게, 배포가 필요한 변경을 끝낼 때마다 이렇게 보고한다:

- 변경 파일을 폴더별로 묶어 적는다: `server/app/`, `server/migrations/`, `data/`, `client/public/gen/`, `client/public/media/`, `server/static/`(= `npm run build` 필요).
- 재시작 필요 여부를 적는다. 필요: `server/app`, `server/migrations`, `data/*`, `gen/manifest.json`. `media/`, `gen/`만 바뀌어도 캐시를 깨는 `asset_version` 때문에 재시작한다 (README 배포 절). 아틀라스 png/json이나 `server/static/`만 바뀐 경우는 새로고침으로 충분하다고 에디터 하단 바가 안내한다 (`tools/preprocess/README.md` "VM 업로드 알림").
- 데이터 리셋이 필요하면 VM 명령을 같이 적는다 (시드 재적용: `seeded:<id>`/`seed_hash:<id>`, 복구 단계 리셋: `stage:<id>`/`stage_ts:<id>`).
- `server/.env`, `interior.db`, venv는 `sync.sh`가 건드리지 않는다. 새 env 변수가 필요하면 VM에서 직접 추가하도록 알린다.
