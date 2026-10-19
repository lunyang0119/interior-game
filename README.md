# Shared Room Decorator

친구들끼리 하나의 방을 같이 꾸미는 작은 웹 게임. Google Sheet의 개인별 재화를 합친 공용 풀로 가구를 사서 놓고, 온라인인 사람들의 아바타가 방을 돌아다닌다.

- 클라이언트: Phaser 3 + Vite + TypeScript (`client/`)
- 서버: FastAPI + SQLite (`server/`)
- 에셋: LimeZu Modern Interiors → `tools/preprocess/`로 전처리 (원본은 gitignore)

## 카탈로그 편집

`data/items.json`이 유일한 소스. 새 가구 추가 절차는 `tools/preprocess/README.md` 참고.
방은 `data/rooms/<id>.json` (에디터 "방" 탭; `inn`은 필수, `seed`/`exits`/`tags` 설명은 같은 README). UI 색/폰트/프레임은 `data/ui_theme.json` (같은 README의 "UI 스킨" 절).

## BGM

`assets/BGM/day/`, `assets/BGM/night/`의 mp3가 기본 BGM으로 한국시간 08:00–18:00 / 그 외로 나뉘어 랜덤 재생된다. 장소별 BGM은 `assets/BGM/<장소>/`에 넣는다 — 장소 이름은 `dock`(낚시터), `field`(필드 지도), `room`(방들). 파일 이름이 `night_`로 시작하면 밤 전용, 아니면 낮 곡이다(`day/`·`night/` 하위 폴더도 계속 된다). 밤 곡이 없는 장소는 밤에도 낮 곡을 틀고, 장소에 곡이 아예 없으면 기본 목록을 쓰며, `legacy/`는 무시된다. 장면이 바뀌면 재생 목록이 실제로 달라질 때만 페이드로 전환된다. 필드 배경은 밤(18:00–08:00)에 어둡게 덮어 그려진다(아직 전용 밤 그림은 없음). 첫 터치 후 시작, HUD 🔊 버튼으로 끄면 기억됨. 테스트용 `?bgm=day|night` 쿼리로 강제 가능.

## 배포 (Oracle Free Tier + Caddy + DuckDNS)

VM에는 Node가 필요 없다. 클라이언트 빌드와 gitignore된 산출물(`gen/`, `media/`, `server/static/`)은 PC에서 만들어 올린다.

**최초 1회 (VM에서)**
```bash
curl -fsSL https://raw.githubusercontent.com/lunyang0119/interior-game/main/deploy/setup-vm.sh | bash
nano /opt/interior/server/.env     # SHEET_URL, DUCKDNS_TOKEN 채우기 (IP_SALT는 자동 생성됨)
```
열차 추적 미니게임(`/train/`, 아래 "열차 추적")을 켜려면 같은 `.env`에 두 줄을 손으로 더한다(스크립트가 넣어 주지 않는다):
```
GEMINI_API_KEY=...                      # 선택. 있으면 열차 추적 로비에서 빈자리를 AI 승무원(Gemini)으로 채울 수 있다 (FUGITIVE_GEMINI_MODEL 로 모델 지정)
TRAIN_ADMIN_SECRET=아무-긴-비밀문구     # 선택. 게임은 누구나 열 수 있고(연 사람이 관제·도주자), 이 문구는 막힌 판을 다른 계정이 넘겨받을 때만 쓴다
TRAIN_WEBHOOK_URL=https://discord.com/api/webhooks/...   # 선택. 게임 시작/체포 문장 두 줄만 보낸다
```
Oracle 콘솔에서 VCN → Security List → Ingress에 TCP 80, 443 추가 (스크립트가 VM 안 iptables는 열어줌).

**배포할 때마다 (PC에서, Git Bash)**
```bash
./deploy/sync.sh ubuntu@crystalroom.duckdns.org            # 클라 빌드 → 서버 코드·마이그레이션·data·gen·static을 tar|ssh로 한 번에 → 재시작
./deploy/sync.sh ubuntu@crystalroom.duckdns.org --media    # BGM·효과음·폰트(client/public/media, 130MB)도 바뀌었을 때
./deploy/sync.sh ubuntu@crystalroom.duckdns.org --no-build --no-restart
```
SFTP로 파일을 하나씩 올리는 대신 쓰는 스크립트다(git은 안 쓴다). VM의 `server/.env`·`interior.db`·venv는 건드리지 않는다. 마지막에 `Active: active (running)`과 `Application startup complete`가 보이면 성공. `~/.bashrc`에 `export VM=ubuntu@crystalroom.duckdns.org`를 적어 두면 주소를 생략할 수 있다. 손으로 올렸을 때는 VM에서 `sudo systemctl restart interior`.

ssh 설정(한 번만, 2026-10-11에 해 둠): Oracle이 만들어 준 개인키(`ssh-key-2025-03-21.key`, Bitvise도 같은 키)를 `~/.ssh/oracle_vm.key`로 복사하고 `~/.ssh/config`에
```
Host crystalroom.duckdns.org 158.179.169.136
  User ubuntu
  IdentityFile ~/.ssh/oracle_vm.key
```
를 넣었다. 새 PC에서는 이걸 다시 하면 된다. `Permission denied (publickey)`가 나오면 키가 없는 것이고, `Host key verification failed`가 나오면 먼저 `ssh ubuntu@crystalroom.duckdns.org`로 한 번 접속해 `yes`를 쳐서 호스트 키를 저장한다(스크립트는 stdin을 tar에 쓰므로 그 질문에 답할 수 없다).

**`media/`(BGM·효과음)나 `gen/`만 바꿨을 때도 재시작**해야 한다 — 브라우저가 `/media/*`·`/gen/*`를 하루 캐시하는데, 재시작해야 캐시를 깨는 버전(`asset_version`: 아틀라스·테마·`bgm.json`·`sfx.json` 해시)이 바뀐다. 안 하면 옛 목록으로 없는 곡을 찾다가 BGM이 조용해질 수 있다.

## 손님 · 숙박료

손님 단위는 **방 전체** 또는, 방에 **구역**(에디터 "구역 그리기", `rooms/<id>.json`의 `zones`)이 있으면 **구역 하나하나**(객실)다. 가구는 왼쪽 위 칸이 들어 있는 구역 소속이고 복도처럼 구역 밖에 놓인 가구는 어디에도 안 들어간다. 단위 키는 `방` 또는 `방:구역`(예: `floor_2:r1`)이고 `/api/rooms`의 `comfort`는 `{단위 키: 뷰}`다.

단위의 **안락도(0–100)** 는 플레이어가 놓은 가구 가격 합(같은 가구는 두 번째부터 절반씩), 방 크기에 따른 포화(단위 넓이 기준이라 작은 객실은 금방 찬다), 같은 세트(출처 팩) 가구가 과반이면 보너스(최대 ×1.5), 부서진 물건 1개당 −5로 계산된다(`server/app/comfort.py`, 수치는 `data/guests.json`). 매일 **KST 09:00 체크아웃**에 잠기지 않은 방의 단위마다 `min(침대 수, 안락도 구간 1~3명)`의 손님이 `4 + 0.36×안락도`💰씩 공동 자금에 넣는다(`ledger.kind='guest'`, 📜 기록 `guest`). `bed` 태그 가구가 없으면 손님 0. 묵고 간 손님은 그 단위 안의 **테이블(is_surface 가구) 위에 쪽지**를 남긴다(안락도 구간별 다른 말, `$guest` 소유라 점수·통행·환불 없음, 단위당 최신 2장). 테이블이 없으면 쪽지도 없다. 서버가 꺼져 있던 날은 최대 3일까지 소급. 가끔 **예약**(특정 가구를 2~4일 안에 놓으면 손님 1명이 2배, 못 놓으면 다음날 손님 없음)과 매달 한 번 **개를 좋아하는 손님**(`dog` 태그 장식이 있거나 안락도 70 이상이면 3배, 아니면 그냥 안 옴)이 온다. 설계 전문: `docs/261009_comfort_design.md`.

여관 벽의 **📋 게시판**(`board` 태그 가구, `inn.json` 시드 `med_018`)을 탭하면 오늘 밤 손님·숙박료 예상, **예약**(요구 가구·남은 날·준비 여부 `reservation.ready`, "상점에서 찾기" 버튼으로 그 가구로 바로 이동), **의뢰**(모든 방의 복구 단계: 지난 단계 ✓, 현재 단계의 진행 막대, 다음 단계, 보상)가 한 화면에 나온다(`client/src/ui/board.ts`). `board` 태그를 다른 가구에 붙이면 그것도 게시판이 된다.

여관에는 **고양이**가 한 마리 산다. 통행 가능한 칸을 혼자 돌아다니며 앉고 두리번거리고 눕는데(클라이언트만 움직임, 서버는 모름), 길을 막지는 않는다. 톡 치면 야옹 소리(`media/sfx/cat.mp3`, `assets/sfx/**/cat_*.mp3`가 있을 때만)가 나고 쓰다듬은 횟수가 쌓인다(클라이언트가 연타를 묶어 `POST /api/cat/pet {taps}`, 한 요청에 최대 50, `cat_taps` 테이블, 모두에게 `{"type":"cat"}` 알림). **애정도 = 모두가 합쳐서 쓰다듬은 횟수 ÷ 100(최대 3), 영구 누적** — 300번이면 영원히 3이다. 한 단계 오를 때만 📜에 `cat` 행이 남고, 📋 게시판과 🛏️ 카드에 `쓰다듬기 n/300`이 보인다. 애정도는 여관(`inn`) 단위의 안락도에 `애정도 × 3`(`guests.json`의 `affection_bonus`)이 더해진다(🛏️ 카드에 `🐱+N`). 다른 방에는 영향이 없다. 고양이 그림은 `assets/graphic/Map/Cats/<변종>.png`에서 `build`가 `gen/cat/`으로 잘라 넣는다(변종은 `tools/preprocess/config.py`의 `CAT_VARIANT`).

**광산**(`data/rooms/mine.json`, `kind: "mine"`인 보통 격자 방 — 여관 '낚시' 단계가 2층과 함께 연다)은 스타듀밸리식 **지하 20층**이다(`data/mine.json` `floors`). 층마다 **매일 KST 자정에 새 레이아웃**이 생긴다(처음 요청될 때 생성, `mine_floors`·`ore_nodes` 테이블): 바위 덩어리(`rocks`의 파티션 슬라이스, `rock_density`; 스폰에서 못 가는 구석은 바위로 메워져 항상 이어진 동굴), 광석 노드 `nodes_per_floor`개(바닥 광석은 바닥 칸, `wall: true` 광석은 뒷벽 맨 아랫줄에 박혀 있고 그 아래 칸에서 캔다), 그리고 **사다리를 숨긴 돌** 하나. 5층 단위 `tiers`가 층별 광석 가중치를 정한다(초안: 1–5층 돌·석탄·청동, 6–10 은 등장, 11–15 금, 16–20 은·금 위주). 모두가 같은 층을 보고(프레즌스 룸은 `mine#층`), 광석을 누르면 아바타가 옆까지 걸어간 뒤 아래 **⛏ 채광** 버튼(스페이스 키도 됨)이 켜진다. 종류마다 눌러야 하는 횟수가 다르고, 누를 때마다 곡괭이 아이콘이 3컷 애니로 휘둘러지며 `media/sfx/pick.mp3`가 난다(`assets/sfx/**/pick_*.mp3`가 있을 때만). 돌(가치 0)을 깨면 그 자리에 **사다리**가 나올 수 있고(층마다 하나는 보장, 나머지 돌은 `ladder_chance`), 밟으면 다음 층으로 내려간다. 한 번 열린 층은 `room_meta mine_deepest:mine`에 영구 기록되어 맵 입구에서 **몇 층으로 갈지 고를 수 있다**(2층 이상 열렸을 때 패널). 여럿이 같은 광석을 쳐도 되고, **마지막으로 친 사람** 이름으로 풀에 입금되며 물고기처럼 120초 안에 납품할 수 있다(복구 need `{"type":"deliver","kind":"mine"}`). 상태 줄은 `n층 · 남은 광석 k/10`, 다 캐면 `n층은 다 캤어요 · 자정에 다시 생겨요`(남은 노드는 다음 날로 넘어가지 않는다). 광산에는 가구를 놓을 수 없고(`no_place`, 상점 버튼 숨김) 손님도 오지 않는다. 광석 그림은 인테리어 아틀라스 슬라이스(`ores[].sprite`)를 그대로 쓰고, `build`가 같은 슬라이스를 `gen/mine/<id>.png`(납품 오버레이)와 `gen/mine/pickaxe_1..3.png`로도 잘라 둔다. 사다리 슬라이스(`ladder` 키)가 아틀라스에 없으면 클라이언트가 어두운 구멍을 그린다.

예약·개파 손님은 `guests.json`의 `special_after`(기본 `room2`)가 열린 뒤부터 온다. 로컬에서 손님을 미리 보려면 `server/.env`에 `DEV_TOOLS=1`을 넣고 서버를 켠 뒤 `POST /api/dev/settle`(`{"days":1,"chance":1}`; 토큰 헤더 필요)을 부르면 그만큼 날이 지난 것처럼 정산된다(`reset:true`로 처음부터, `dog:true`로 개파 손님 다시 추첨). VM에는 절대 켜지 말 것. 정산 상태는 `room_meta`의 `guest_day:<단위>`(마지막 정산일), `no_guests_day:<단위>`, `dog_month`와 `reservations` 테이블에 있다. 처음 켜진 날은 "오늘부터 센다"라 돈이 소급되지 않는다.

아직 안 열린 장소(복구 단계가 남은 방·광산)를 디버깅하려면 `DEBUG_PLAYERS`(env, 쉼표 구분, 기본 `안나`) 계정으로 들어가면 된다. 서버는 그 계정의 ws `enter`만 통과시키고 가구 배치는 여전히 거부하며, 클라이언트 `state.ts`의 `isDebugAccount()`가 같은 목록을 미러링해 맵 문·입장 잠금을 건너뛴다.

**맵 바꿀 때 (VM에서)**
```bash
sudo systemctl stop interior
grep DB_PATH /opt/interior/server/.env
sqlite3 <그 경로> "DELETE FROM room_meta WHERE k IN ('seeded:room2','seed_hash:room2');"
# 복구 단계를 처음부터 다시 하고 싶으면 (납품 기록은 남음)
sqlite3 <그 경로> "DELETE FROM room_meta WHERE k LIKE 'stage:%' OR k LIKE 'stage_ts:%';"
sudo systemctl start interior
```
  로그에 seeded room inn: N items (M old seed rows replaced)가 나오면 된 거

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/register` | 닉네임으로 로그인/등록. DB에 있는 ID면 새 토큰 발급(이전 토큰 무효), 없으면 시트 R열에 기록(없으면 새 행) 후 생성 |
| GET | `/api/me` | 내 정보 + 공용 잔액 + 기여 목록 |
| POST | `/api/sync` | 시트 강제 동기화 |
| PUT | `/api/avatar` | 아바타 레이어 인덱스 |
| GET | `/api/catalog` | 아이템/방/캐릭터 메타 |
| GET | `/api/rooms` | 방 목록: 버전, 남은 `ruined` 개수, 접속자 수, 복구 `progress`(단계 수·현재 단계의 need별 진행), `comfort`(안락도·침대 수·오늘 밤 예상 손님/숙박료·예약; 잠긴 방은 null), 최상위 `locked`(아직 못 들어가는 장소) |
| GET | `/api/activity` | 📜 기록: 최근 이벤트 **5개만**(서버가 더는 안 줌), 오늘 요약(벌이·지출·낚시·채광 수), 모든 방의 복구 진행, `comfort`(방별 안락도·손님 뷰) |
| POST | `/api/deliver` (`seq`, `room?`) | 방금 낚은 물고기(`/api/fish/finish`의 `seq`)나 방금 캔 광석(`/api/mine/hit`의 `ledger_seq`)을 팔지 않고 어떤 방의 복구 단계에 **납품**. 120초 안에 1번만, 그 돈은 풀에서 다시 빠짐(`ledger.kind='deliver'`) |
| GET `/api/mine` · GET `/api/mine/floor/{n}` · POST `/api/mine/hit` (`seq`) | 광산: 광석 종류표 + 열린 최대 층(`deepest`) / n층의 오늘 레이아웃(바위·노드·사다리; 아직 안 열린 층은 403 `floor_locked`) / 채광 한 번. 아바타가 그 층(`mine#n`)에서 노드 옆(`reach`칸)에 있어야 하고(`not_here`), 마지막 타격이 풀에 입금(`ledger.kind='mine'`) + 같은 층 사람에게 `{"type":"mine"}` 알림, 돌이 사다리를 숨기고 있었으면 `ladder`. 설정은 `data/mine.json` |
| GET | `/api/room/{id}` (`/api/room` = inn) | 방 아이템 + `ruined` (ETag = 방 버전) |
| PUT | `/api/room/item/{uid}/note` `{text}` | `note` 태그 아이템(메모지·칠판·게시판)에 글 남기기(200자, 빈 문자열이면 지움). 누구나 고쳐 쓸 수 있고 방 버전이 올라가 모두에게 갱신 |
| POST | `/api/room/place` (`room_id`) · `/api/room/move` · DELETE `/api/room/item/{uid}` | 배치/이동/삭제 (서버가 규칙 검증). `ruined`/`fixed` 태그는 구매 불가(`not_for_sale`), `fixed`는 이동·삭제도 불가(`fixed_item`) |
| GET `/api/fish` · POST `/api/fish/start` · `/api/fish/finish` | 부두 낚시: 서버가 입질 일정을 만들고(진짜 1번 + 미끼 건드림), 클라가 버튼을 누른 구간을 보내면 판정. 잡으면 공용 풀에 바로 입금(`ledger.kind='fish'`) + 전원 알림. 설정은 `data/fishing.json` |
| POST | `/api/token/rotate` · GET `/api/me/logins` | 토큰 재발급 / 접속 기록 |
| WS | `/ws` | 온라인 아바타 위치(같은 방끼리), `enter`로 방 이동, 방 변경 알림(전체) |
| `/api/train/*` · WS `/ws/train` | 열차 추적 미니게임 (아래) |

## 열차 추적 (/train/)

디스코드 봇의 "침입자 추적" 규칙 엔진(`server/app/train/engine.py` 등, 봇 레포 commit 2182a11 그대로 복사, 수정 금지)을 웹으로 올린 격리 미니게임. 본 게임과는 계정·토큰(`localStorage`)만 공유하고 방·돈·presence는 전혀 섞이지 않는다. 한 번에 한 판, 상태는 `train_games`(마이그레이션 016)에 전환마다 통째로 저장되어 재시작해도 라운드 마감이 그대로 이어진다(PAUSED 는 타이머 없이 복원).

- **역할**: 진행 중인 판이 없을 때 `POST /api/train/game`을 부른 계정이 그 판의 **도주자 = 관리자**가 된다(`train_meta.admin_id`에 저장, 재시작해도 유지). `POST /api/train/claim {secret}`(`TRAIN_ADMIN_SECRET`, 선택)은 같은 역할을 다른 계정으로 강제로 옮기는 비상용이다. 로비에 `join`한 사람이 헌터, 나머지 로그인 사용자는 관전자(헌터와 같은 공개 뷰만). 헌터/관전자에게는 도주자 위치·RAM·경로(`fugitive_path`)가 어떤 응답에도 들어가지 않는다(테스트 `test_train.py`가 키 단위로 확인).
- **흐름**: 관리자 `POST /game {hunter_count, map_id?, overrides?}` → 헌터 `POST /join` → `POST /start`(라운드 1 열림, 디스코드에 `Activating Combat Mode`) → 라운드마다 헌터 `POST /order {type, target?}`, 도주자 `POST /fugitive/order {move?, hack?, target?}` / `POST /fugitive/ping` → 전원 제출 시 조기 정산(도주자가 미제출이면 `fugitive_grace_sec` 유예) 또는 마감(`round_timer_sec`, 기본 1시간) 시 미제출자 대기 처리 → 체포되면 디스코드에 체포 문장 한 줄. 헌터의 명령 내용은 헌터·관전자에게 공개, 도주자는 핑을 써야 그 라운드의 명령을 본다.
- **AI 승무원**: 봇 레포의 `bot_player.py`/`render.py`(역시 commit 2182a11 그대로 복사)를 써서 로비의 빈자리를 Gemini 헌터로 채운다. 관제가 `POST /api/train/bots {target_count}`(로비에서만, `DELETE /bots`로 전부 내림) → 로비 id `bot:N`(화면에는 `제미나이-N`). 라운드가 열릴 때마다 서버가 백그라운드로 봇마다 Gemini에 한 번 묻고 그 명령을 일반 헌터처럼 제출한다(규칙 위반 답이면 대기, API 실패도 대기). 봇의 프롬프트는 헌터가 볼 수 있는 공개 뷰만 담고, 판단 이유(`bot_reasons`, ws `bot_thinking`/`bot_reason`)는 도주자에게만 간다. `GEMINI_API_KEY`가 없으면 버튼이 숨고 404 대신 503 `ai_unavailable`.
- **AI 도주자**: 추적을 열 때 "도주자도 AI"를 켜거나 로비에서 `POST /api/train/fugitive-ai {on}`(관제, 로비에서만). 그 판은 Gemini가 도주자 명령(이동+퀵핵)을 라운드마다 제출하고(`bot_player.decide_fugitive`, 규칙 위반 답이면 이동만 또는 대기), 연 사람은 **관제 권한(일시정지·튠값·AI 승무원)은 그대로** 두고 도주자 화면(실제 위치, AI 판단 이유)을 지켜보며, `join`으로 탑승하면 그때만 승무원 뷰가 된다(페이로드 `admin` = 권한, `role` = 보는 뷰). 도주자 API(`/fugitive/*`, `/ping`)는 403 `fugitive_is_ai`. AI들의 판단 이유는 체포된 뒤 모두에게 `ai_log`로 공개된다. AI 승무원 + AI 도주자를 같이 켜면 사람 하나(또는 0명)로도 판이 돈다.
- **투표로 건너뛰기**: 라운드가 열린 뒤 `vote_skip_after_sec`(기본 600초)이 지나면 `POST /vote {target}`으로 미제출 헌터를 "대기"로 넘길 수 있다. 다른 헌터의 과반(2명이면 1표, 4명이면 2표)이면 통과, 대상이 먼저 제출하면 무효, 라운드마다 초기화.
- **관리자**: `GET/PUT /config`(엔진 튠값 즉시 반영, 맵은 로비에서만), `POST /pause` `/resume` `/extend {sec}` `/round/end` `/game/end`, `GET /maps` `/maps/{id}`(공개, 미리보기 `/train/?preview=car2077_12`).
- **UI**: `/train/`만 사이버펑크 GUI(`assets/graphic/GUI/cyberpunk GUI`)를 쓴다. `python tools/preprocess/preprocess.py train-ui`가 프레임 3장을 여백 없이 잘라 `client/public/media/train/`에, 아이콘 시트를 격자로 잘라 `icons.png`에 담고, 9-slice 변수와 `.ic-<이름>` 클래스를 `client/src/train/cyber.css`(생성 파일, 커밋함)로 쓴다. `<html class="train">`에서만 테마를 덮어쓰므로 방 게임 UI는 그대로. 슬라이스 경계·아이콘 이름은 `tools/preprocess/train_ui.py`의 `SLICES`/`ICON_NAMES`. 같은 명령이 `config.TRAIN_FUGITIVE_SHEET`(캐릭터 생성기 레이아웃 시트, 기본 `0_Premade_Characters/16x16/bonwa1.png`)를 `media/train/fugitive.png`로 잘라 도주자 실루엣 스프라이트로 쓴다(파일이 없으면 기본 레이어 실루엣). 추적·목격 결과는 재생 뒤 HUD 아래 토스트 하나로 합쳐 뜨고 탭하면 닫힌다.
- **QoL (2026-10-14)**: 탭 제목 뱃지(내 차례/새 결과), 미제출자 이름 + 투표 버튼, 상대 시간 표시, 판독 기록 패널(건너뛰기·다시 보기, 라운드별 스크롤), HUD의 내 명령 + 바꾸기, 도움말 패널(`GET /api/train/help` = strings.TUTORIAL/HELP 웹용 재구성 + 표식 범례, 첫 방문에 자동), 퀵핵 불가 사유와 추적률 예측, 체포 후 `POST /api/train/reveal {on}`으로 도주자 경로 공개(페이로드 `route`, CAPTURED + on 일 때만), 재생이 없을 땐 Phaser 10fps·탭 숨김 시 루프 정지, 추적률 단계별 BGM(`client/src/train/bgm.ts`의 `TRAIN_BGM` 한 곳: 임계값 25/50/75와 자리표시 트랙, 정산 때만 크로스페이드), 라운드 시작 효과음·진동, 출발 3초 카운트다운, 관제 패널 위험 버튼 2단계 확인.
- **끝나는 방법 두 가지**: 승무원이 도주자를 잡으면 체포(승무원 승), 신호가 동결되기 전에 못 잡으면 `ESCAPED` 상태로 도주자 탈출(도주자 승, 정책 `escape_on_freeze`, ws `escaped`). 체포 조건은 도주자가 있는 방 수색, 또는 같은 라운드에 도주자와 같은 문 통과(마주 지나든 뒤따르든)이고, 수색 없이 같은 방에서 끝나면 목격만 된다. 추적(scan)은 정산 뒤 도주자가 있는 방의 장치 계열을 알려준다(`scan_lag` 0).
- **설정 층**: 엔진 `DEFAULTS` → `server/app/train/scaling_web.json[좌석 수]` → 웹 기본(`WEB_DEFAULTS`: `round_timer_sec 3600`, `early_resolve` 등) → `data/train_config.json`(선택; 평평한 `{키: 값}` 다음에 좌석 수별 섹션 `"2"`..`"6"`) → 관리자 런타임 오버라이드. 맵·밸런스는 좌석이 아니라 실제로 탑승한 인원 수로 고른다. 시트는 쓰지 않는다. 밸런스 시뮬: `cd server && python -m app.train.sim --all --games 400 --seed 1 --scaling app/train/scaling_web.json`.
- **배포 메모**: AI(Gemini)를 쓰려면 VM에서 `pip install -e .`로 `google-genai`를 설치하고 `.env`에 `GEMINI_API_KEY`(`server/.env.example` 참고). 올리기 전에 `python tools/preprocess/preprocess.py train-ui`로 `media/train/`(png + icons.json)을 만들고 `npm run build` 한다. `data/train_interiors.json`·`data/train_maps.json`을 바꾸면 서비스 재시작이 필요하다.

복구 링크: `https://도메인/?t=TOKEN` — 열면 토큰이 localStorage로 옮겨지고 URL에서 지워진다.

# 에러 로그 보는 법

## 502 떴을 때 (제일 먼저)
  journalctl -u interior -n 60 --no-pager   # 마지막 60줄, 페이저 없이 — 보통 기동 중 ImportError/ValueError가 여기 있음
  systemctl status interior --no-pager      # 죽어 있는지, 몇 번 재시작했는지

  새 파일을 빼먹고 올렸을 때(`cannot import name ...`)나 data/ 검증 실패(`ValueError: room ...`)가 대부분. 고친 뒤 `sudo systemctl restart interior`.

## 실시간으로 보기 (tail -f 같은 느낌)
  journalctl -u interior -f

## 자주 쓰는 것들
  journalctl -u interior -n 200            # 최근 200줄
  journalctl -u interior --since "1 hour ago"
  journalctl -u interior --since today
  journalctl -u interior -p warning        # WARNING 이상만 (에러 찾을 때)
  journalctl -u interior -g "removed item" # grep처럼 검색
  journalctl -u interior --no-pager | less # 페이저 없이 전체

  -f로 켜둔 채 폰에서 조작해 보면 place/move 에러가 바로 찍힘. 파이썬 예외 트레이스백도 여기 다 들어감.

### 영구 보관 확인
  Ubuntu 기본은 journald가 /var/log/journal/에 영구 저장인데, 혹시 재부팅하면 사라지는 상태면 한 번만:
  sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald

### 앱 로그가 너무 적다면
  지금 main.py에 logging.basicConfig(level=logging.INFO)라 INFO까지는 나와. 요청별 에러(ApiError)는 access_log 테이블에도 성공/실패로 남으니, journald에서 안 보이면 sqlite3 interior.db
  "select * from access_log order by ts desc limit 50"로 봐도 돼.