# 맥북 24h RD 자동화 셋업 (맥 초보용)

> 목표: 구형 맥북을 켜두면 **매일 자동으로 키워드 RD + 낙찰가 + 번역**이 수집되어 Supabase(공용 DB)에 쌓이게.
> GPU·AI·유료 API 안 씀 — 전부 브라우저 + 무료. (윈도우 PC와 같은 DB에 적재됨)

맥 명령은 전부 **터미널**에 칩니다. 터미널 여는 법: **`Cmd`+`Space` → "터미널" 입력 → Enter.**
명령은 한 줄씩 복사 → 붙여넣기(`Cmd`+`V`) → Enter.

---

## 0단계 · 준비 (GUI로 설치, 한 번만)

1. **Google Chrome 설치** — 사파리로 `google.com/chrome` 접속 → 다운로드 → 받은 `.dmg` 열기 → Chrome 아이콘을 **응용 프로그램** 폴더로 드래그.
2. **Python 3 확인** — 터미널에 `python3 --version` → `Python 3.x.x` 나오면 OK.
   안 나오면 `python.org/downloads` 에서 macOS 설치 파일 받아 설치.

---

## 1단계 · 코드 받기

터미널에 그대로:

```bash
cd ~
git clone https://github.com/handsombros-arch/qoo10-keyword-extractor.git
```

> 처음 `git` 쓰면 "개발자 도구 설치" 팝업이 뜹니다 → **설치** 누르고 끝나면 위 명령 다시 실행.

---

## 2단계 · 자동 셋업 실행

```bash
bash ~/qoo10-keyword-extractor/automation/mac/setup.sh
```

→ 가상환경 만들고 패키지 설치(수 분). 끝에 안내가 나옵니다.

---

## 3단계 · DB 연결값(.env) 넣기 ★필수★

RD 자동화에 **꼭 필요한 건 `DATABASE_URL` 한 줄**(Supabase 주소)입니다.
윈도우 PC 의 `backend/.env` 파일을 열어 **`DATABASE_URL=...` 줄을 복사**해 두세요.

맥 터미널에서:

```bash
nano ~/qoo10-keyword-extractor/backend/.env
```

편집기가 열리면 복사한 `DATABASE_URL=...` 줄을 붙여넣기 → **저장**(`Ctrl`+`O` → Enter) → **나가기**(`Ctrl`+`X`).

> 윈도우 .env 전체를 복사해 넣어도 됩니다(나머지 키는 RD엔 안 쓰이지만 무해).

---

## 4단계 · 백엔드 켜고 큐텐 로그인 (한 번만)

```bash
launchctl load ~/Library/LaunchAgents/com.elviten.backend.plist
```

→ 잠시 뒤 **Chrome 창이 자동으로 뜹니다.**
→ 큐텐(QSM)에 **로그인 1회** 하세요. (이후엔 쿠키가 저장돼 자동 로그인)
→ **그 Chrome 창은 닫지 마세요.** 24시간 서버용입니다.

로그인 됐는지 확인:

```bash
curl -s http://127.0.0.1:8000/api/auth/status
```

→ `"logged_in":true` 나오면 성공.

---

## 5단계 · 수동으로 한 번 돌려보기 (검증)

```bash
cd ~/qoo10-keyword-extractor
backend/venv/bin/python automation/trigger_daily_rd.py --cats 3,7
```

- `--cats 3,7` = 뷰티(3) + 식품(7). **전 카테고리 원하면** `--cats 1,2,3,4,5,6,7,8,9,10,11,12`
- 낙찰가 빼고 빠르게 = 끝에 `--no-bids`
- 수 분 후 끝납니다. 윈도우 엘비텐 화면에서 **오늘 날짜 데이터가 들어왔는지** 확인하세요.

---

## 6단계 · 매일 자동 켜기

```bash
launchctl load ~/Library/LaunchAgents/com.elviten.rd-daily.plist
```

→ 이제 **매일 새벽 4시**에 자동 수집됩니다.
시간 바꾸려면 `nano ~/Library/LaunchAgents/com.elviten.rd-daily.plist` 에서 `<integer>4</integer>`(시) 수정 후
`launchctl unload ...` → `launchctl load ...` 다시.

수집 카테고리 바꾸려면 같은 파일의 `<string>3,7</string>` 를 원하는 번호로.

---

## 7단계 · 맥북 잠들지 않게 (중요)

맥북이 자면 수집이 멈춥니다. **전원 연결** 후 터미널에:

```bash
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
```

(암호 입력 — 화면엔 안 보임, 그냥 치고 Enter)
또는 **시스템 설정 → 배터리/잠금화면**에서 자동 잠자기를 "안 함"으로.

---

## 자주 쓰는 명령 / 문제 해결

| 하고 싶은 것 | 명령 |
|---|---|
| 백엔드 살아있나 | `curl -s http://127.0.0.1:8000/api/auth/status` |
| 로그인 다시 (세션 풀림) | `curl -s -X POST http://127.0.0.1:8000/api/auth/verify` |
| 백엔드 로그 보기 | `tail -f ~/qoo10-keyword-extractor/logs/backend.err.log` |
| 야간 수집 로그 보기 | `tail -f ~/qoo10-keyword-extractor/logs/rd_daily.log` |
| 지금 즉시 수집 | `cd ~/qoo10-keyword-extractor && backend/venv/bin/python automation/trigger_daily_rd.py --cats 3,7` |
| 백엔드 끄기 | `launchctl unload ~/Library/LaunchAgents/com.elviten.backend.plist` |
| 자동수집 끄기 | `launchctl unload ~/Library/LaunchAgents/com.elviten.rd-daily.plist` |
| 코드 업데이트(윈도우서 커밋 후) | `cd ~/qoo10-keyword-extractor && git pull && launchctl unload ~/Library/LaunchAgents/com.elviten.backend.plist && launchctl load ~/Library/LaunchAgents/com.elviten.backend.plist` |

### 잘 안 될 때
- **Chrome 창이 안 뜸 / 로그인 안 됨** → `4단계` 다시. 그래도 안 되면 백엔드 로그(`backend.err.log`) 확인.
- **수집 0건** → 큐텐 로그인 풀렸을 수 있음 → `verify` 명령. 또는 큐텐 사이트 구조 변경(셀렉터 노후) → 윈도우에서 점검 필요.
- **DB 안 들어감** → `.env` 의 `DATABASE_URL` 확인 (3단계).

> 막히면 어느 단계에서 무슨 메시지가 나왔는지 알려주세요 — 그 지점부터 잡겠습니다.
