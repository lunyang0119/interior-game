# 열차 추적 플레이테스트 준비 (2026-10-14)

## 1. VM 배포 체크리스트

```bash
# PC(Git Bash, 레포 루트)에서. 클라이언트 빌드 → tar | ssh → /opt/interior → 서비스 재시작
./deploy/sync.sh ubuntu@<host> --media     # media/train/*.png(사이버펑크 UI)가 처음 올라가니 이번엔 --media 필수
# 이후엔 ./deploy/sync.sh ubuntu@<host> 만으로 충분 (server/app, migrations, data, gen, static)
```

sync 전에 VM `server/.env`에 웹훅 주소를 직접 추가해 둔다(sync는 .env를 절대 건드리지 않음). 관제 비밀문구는 선택이다:
게임은 누구나 열 수 있고 연 사람이 그 판의 관제·도주자가 된다. 문구는 막힌 판을 다른 계정이 넘겨받을 때만 쓴다.

```
TRAIN_WEBHOOK_URL=https://discord.com/api/webhooks/...
GEMINI_API_KEY=<키>               # 선택: 로비의 빈자리를 AI 승무원(Gemini)으로 채우는 버튼이 생긴다
TRAIN_ADMIN_SECRET=<긴 비밀문구>   # 선택
```

새 파이썬 의존성(`google-genai`)이 생겼다. sync는 패키지를 설치하지 않으므로 VM에서 한 번:

```bash
cd /opt/interior/server && .venv/bin/pip install -e . && sudo systemctl restart interior
```

VM에서 확인:

```bash
# (1) 마이그레이션 016 적용 여부: user_version이 16 이상이고 train_games 테이블이 있어야 함
sqlite3 /opt/interior/server/interior.db 'PRAGMA user_version; .tables' | tr ' ' '\n' | grep -E '^[0-9]+$|train_'

# (2) 환경변수가 "프로세스에" 로드됐는지 — 이름만 출력, 값은 절대 안 찍힘
sudo cat /proc/$(systemctl show -p MainPID --value interior)/environ | tr '\0' '\n' | grep -o '^TRAIN_[A-Z_]*=' 
#   기대: TRAIN_WEBHOOK_URL= (+ 넣었다면 GEMINI_API_KEY= / TRAIN_ADMIN_SECRET=)   없으면 .env 저장 후 sudo systemctl restart interior
#   Gemini 키가 프로세스에 들어갔는지는 /train/ 로비에 "AI 승무원으로 채우기" 버튼이 보이는지로도 알 수 있다
# .env 파일 쪽도 값 없이: grep -c '^TRAIN_ADMIN_SECRET=.' /opt/interior/server/.env   → 1

# (3) 서버가 켜졌고 라우터가 붙었는지 (401 = 정상: 인증 없이 호출)
curl -s -o /dev/null -w '%{http_code}\n' https://crystalroom.duckdns.org/api/train/state

# (4) 게임 중 로그 보기 (train 줄만)
journalctl -u interior -f -o cat | grep --line-buffered -i train
#   볼 것: "train: restored game" (재시작 시), "train webhook" 경고(발송 실패), 라운드 정산 오류
```

브라우저에서의 최종 확인: `/train/` 접속 → 탑승 패널에 `새 추적 열기`가 보이면 된다.

웹훅 확인: 게임 시작 시 Discord에 COMBAT_MODE_ON 한 줄이 와야 한다. 안 오면 journalctl에 `train webhook: HTTP ...` 또는
`train webhook failed:`가 찍힌다(정산은 영향 없음).

## 2. 혼자 하는 스모크 테스트 (계정 2개 + AI 승무원 1)

완전 혼자(계정 1개)로 돌려 보려면: 추적 열 때 "도주자도 AI" 체크 → 내가 `탑승` → `AI 승무원으로 채우기` → `출발`. 도주자 쪽 화면(핑·퀵핵·실루엣 실제 위치)은 이 모드에선 아무도 못 보고, 체포 뒤 판독 보고 패널에 AI들의 판단 기록이 공개된다. 아래 절차는 도주자를 사람(A)이 맡는 기본 모드 기준.

엔진 최소 추적자 수가 2라서 추적자가 둘 필요하다. `GEMINI_API_KEY`가 있으면 **C는 AI 승무원**으로 채우면 되고,
브라우저 프로필은 2개면 된다: **A = 관제·도주자**, **B = 추적자 1**, **C = 제미나이-1 (AI)**. 각 창에서 `/`로 먼저 로그인한 뒤 `/train/`으로.
(키가 없으면 C를 시크릿 창이나 폰의 세 번째 계정으로.)

1. **로비 열기** — A: 탑승 패널에서 `2명` 선택, 맵은 "인원에 맞게" → `새 추적 열기`. A가 자동으로 관제·도주자가 되고 관제(톱니) 버튼이 생긴다(비밀문구 불필요).
2. **탑승** — B: 탑승 버튼 → `탑승`. A: 탑승 패널 `AI 승무원으로 채우기 (1명)` → 목록에 🤖 제미나이-1, `승무원 2/2명`. (`AI 승무원 내리기`로 되돌릴 수 있다.)
3. **테스트 프리셋** — A: 관제 → 맨 아래 `테스트 프리셋 (2분·투표 30초·유예 30초)`. 키 세 개가 굵게 표시되면 적용된 것(이 판에만, `train_config.json`은 그대로).
4. **출발** — A: 탑승 패널 `출발 (라운드 1 시작)`. 세 창 모두 HUD가 `R1`, 타이머 2:00. **Discord에 COMBAT_MODE_ON 줄 확인.**
5. **R1 기본 제출** — 라운드가 열리면 A에게 "🤖 제미나이-1 — R1 판단 중…" 토스트, 몇 초 뒤 선택과 이유 토스트(판독 보고 패널 아래 "AI 승무원의 판단"에도 남는다). B: 방 탭 → `이번 라운드 행동 확정`. A: 방/문 탭 → 확정. 전원 제출 즉시 정산 → 재생(아바타 걷기) → 판독 보고 패널.
6. **R2 행동 변경** — B: 수색 확정 후 다른 방 탭 → `바꾼 행동으로 확정` 버튼이 뜨는지. 그대로 다시 확정.
7. **R2 투표 건너뛰기** — AI는 바로 제출하므로 투표를 보려면 B가 제출하지 않은 채 기다린다: A의 HUD에는 아무것도 없고, 이 테스트는 사람 추적자가 둘일 때(C를 세 번째 계정으로 넣었을 때) C 미제출 → B의 HUD 트로피 버튼이 30초 카운트다운 → `건너뛰기` → 투표 패널에서 C에 찬성. 추적자 2명이라 1표면 통과, C는 `대기`로 자동 제출되고 정산된다. AI만 있는 판이면 이 단계는 건너뛴다.
8. **R3 일시정지/재개** — A: 관제 → `⏸ 일시정지`. 세 창 HUD가 `일시정지`, 행동 버튼 비활성. 30초쯤 뒤 `▶ 재개` → 남은 시간이 멈췄던 값에서 이어지고 투표 카운트다운도 그만큼 밀렸는지.
9. **R3 핑** — A: 행동 패널 `핑 (비용)` 버튼 → RAM이 줄고, 추적자 패널(hunters_full)에 B·C의 제출 내용이 보인다. 핑을 안 쓴 라운드에서는 "제출함" 표시만 보여야 한다.
10. **체포** — A가 일부러 B와 같은 방에 머물고 B가 그 방을 수색. 정산 재생 끝에 실루엣의 검은 틴트가 풀리고 배너에 CAPTURE_LINE. **Discord에 체포 줄 1개**(중복 없이).
11. **재접속 재생** — 체포 전 아무 라운드에서: B 창을 새로고침 → 방금 라운드 재생이 다시 돌면 안 되고(이미 본 라운드, `localStorage train_played`), 다른 창에서 라운드를 하나 더 정산한 뒤 B를 새로고침 → 그 라운드만 재생돼야 한다.
    서버 재시작 확인까지 하려면: 라운드 열린 채로 `sudo systemctl restart interior` → 타이머가 저장된 마감으로 이어지는지, 일시정지 중 재시작 → 그대로 일시정지인지.
12. **정리** — A: 관제 → `추적 종료`(IDLE로). 다음 판 전에 `기본값으로`를 누를 필요는 없다(새 판은 덮어쓴 값 없이 시작).

막히면: `journalctl -u interior -f -o cat | grep -i train` 을 옆에 켜 두고 토스트 문구와 같이 보기.

## 3. 시뮬레이터: trace_t1=55, trace_t2=85 (scaling_web.json, 400판, seed 1·2)

현재 기본값 trace_t1=40, trace_t2=70. 값은 p50 라운드 / 동결 뒤 종료 비율(frz%). 설정은 아직 안 바꿨다.

| N | 봇 | 현재 seed1 | 현재 seed2 | 새값 seed1 | 새값 seed2 |
|---|---|---|---|---|---|
| 2 | hacker  | 9.0 / 100.0 | 9.0 / 100.0 | 9.0 / 100.0 | 9.0 / 100.0 |
| 2 | stealth | 10.0 / 91.5 | 10.0 / 89.2 | 10.0 / 100.0 | 10.0 / 100.0 |
| 3 | hacker  | 8.0 / 99.5 | 8.0 / 99.5 | 8.0 / 97.0 | 8.0 / 97.5 |
| 3 | stealth | 10.0 / 88.2 | 10.0 / 89.8 | 10.0 / 91.8 | 10.0 / 89.2 |
| 4 | hacker  | 10.0 / 72.2 | 10.0 / 74.0 | 10.0 / 72.0 | 10.0 / 71.5 |
| 4 | stealth | 8.0 / 38.5 | 8.0 / 39.8 | 6.0 / 36.8 | 9.0 / 44.2 |
| 5 | hacker  | 9.0 / 88.5 | 9.0 / 89.5 | 8.0 / 85.0 | 8.0 / 81.5 |
| 5 | stealth | 10.0 / 59.0 | 10.0 / 62.5 | 10.0 / 60.2 | 10.0 / 65.2 |
| 6 | hacker  | 10.0 / 70.8 | 10.0 / 68.2 | 9.0 / 68.2 | 9.0 / 67.5 |
| 6 | stealth | 9.0 / 29.0 | 10.0 / 36.0 | 10.0 / 39.2 | 9.0 / 38.2 |

재현: `cd server && python -m app.train.sim --all --games 400 --seed 1 --scaling app/train/scaling_web.json --set trace_t1=55 --set trace_t2=85`
