# Shared Room Decorator

친구들끼리 하나의 방을 같이 꾸미는 작은 웹 게임. Google Sheet의 개인별 재화를 합친 공용 풀로 가구를 사서 놓고, 온라인인 사람들의 아바타가 방을 돌아다닌다.

- 클라이언트: Phaser 3 + Vite + TypeScript (`client/`)
- 서버: FastAPI + SQLite (`server/`)
- 에셋: LimeZu Modern Interiors → `tools/preprocess/`로 전처리 (원본은 gitignore)

## 로컬 개발

```bash
# 0. 에셋 (한 번만) — assets/ 에 LimeZu 팩을 둔 뒤
python tools/preprocess/preprocess.py build

# 1. 서버 (가짜 시트 data/fake_sheet.json 사용)
cd server
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # mac/linux: .venv/bin/pip
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload

# 2. 클라이언트 (핫 리로드, /api·/ws 는 8000으로 프록시)
cd client
npm install
npm run dev        # http://localhost:5173  (폰: 같은 와이파이에서 --host 주소)
```

프로덕션 빌드는 `npm run build` → `server/static/`에 생성되고 FastAPI가 같은 오리진에서 서빙한다.

## 카탈로그 편집

`data/items.json`이 유일한 소스. 새 가구 추가 절차는 `tools/preprocess/README.md` 참고.
방 크기/타일은 `data/room.json`.

## 배포 (Oracle Free Tier + Caddy + DuckDNS)

1. VM에 `git clone` → `/opt/interior`, Python 3.11+, Node 20+ (또는 로컬 빌드 후 `server/static` rsync), Caddy 설치.
2. `client/public/gen/`은 gitignore라 PC에서 한 번 rsync.
3. `server/.env.example` → `server/.env` 채우기 (`SHEET_URL`, `IP_SALT`).
4. `deploy/interior.service` → `/etc/systemd/system/`, `deploy/Caddyfile` → `/etc/caddy/Caddyfile` (도메인 수정).
5. `deploy/duckdns.sh` 토큰 채우고 cron 등록. Oracle 보안 목록에서 80/443 열기 (+ VM 내부 iptables).
6. `sudo systemctl enable --now interior caddy`, 이후 업데이트는 `./deploy/deploy.sh`.

Apps Script 코드는 `tools/appsscript/Code.gs`. 시트 탭 이름/컬럼만 상수로 맞추면 됨.

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/register` | 시트에 있는 ID로 등록 → 토큰 1회 발급 |
| GET | `/api/me` | 내 정보 + 공용 잔액 + 기여 목록 |
| POST | `/api/sync` | 시트 강제 동기화 |
| PUT | `/api/avatar` | 아바타 레이어 인덱스 |
| GET | `/api/catalog` | 아이템/방/캐릭터 메타 |
| GET | `/api/room` | 방 아이템 (ETag 지원) |
| POST | `/api/room/place` · `/api/room/move` · DELETE `/api/room/item/{uid}` | 배치/이동/삭제 (서버가 규칙 검증) |
| POST | `/api/token/rotate` · GET `/api/me/logins` | 토큰 재발급 / 접속 기록 |
| WS | `/ws` | 온라인 아바타 위치, 방 변경 알림 |

복구 링크: `https://도메인/?t=TOKEN` — 열면 토큰이 localStorage로 옮겨지고 URL에서 지워진다.
