# SSRF → Redis → SSH 키 주입 → 배스천 오설정 → sudo 권한상승 훈련용 격리 랩

Red/Blue Team 교육 및 CTF 훈련을 위한 **격리된 로컬 Docker 환경**입니다. 실제 이커머스 사이트처럼 보이는
`ec-site`, 내부망 전용 `proxy-server`(Squid + Redis + SSH 배스천), 그리고 공격자 시점을 재현하는
`attacker` 컨테이너로 구성되어 있습니다.

> ⚠️ 이 환경은 **의도적으로 취약하게 설계**되었습니다. 격리된 Docker 네트워크 밖으로 절대 노출하지 마세요.
> 실제 운영 환경의 자격증명/도메인/외부 IP는 포함되어 있지 않습니다.

## 설계 의도: 두 가지 독립된 결함이 겹쳐야만 침투가 완성된다

이 랩은 **어느 한쪽만으로는 안전하다는 흔한 착각 두 가지**를 짚기 위해 만들어졌습니다.

1. **네트워크 세그멘테이션 결함 (배스천 오설정)**: `proxy-server`는 관리 목적의 SSH(22번)만 예외적으로
   `mgmt-net`에 노출합니다. "관리 포트만 배스천으로 열어둔다"는 아키텍처 자체는 업계 표준이지만, **접근
   소스 IP를 제한하지 않아** 사실상 그 네트워크에 있는 누구나 SSH 포트까지는 도달할 수 있습니다. 이것만
   보면 "어차피 키가 없으면 못 들어간다"고 안심하기 쉽습니다.
2. **인증정보 유출 경로 (SSRF → Redis 미인증 접근)**: 실제로 유효한 키가 없으면 1번은 무해합니다. 하지만
   공격자는 완전히 별개의 SSRF 취약점을 통해 내부 Redis에 미인증으로 접근해 유효한 SSH 공개키를
   주입함으로써, 1번의 네트워크 결함을 실제 침투로 전환시킵니다.

즉 이 랩의 교훈은 "네트워크 결함 하나만으로는 안전하지 않다"와 "인증키만 있으면 안전하다는 가정은
그 키가 어떻게 발급/저장되는지에 달려 있다"는 두 가지입니다. 둘 중 하나만 고쳐도(소스 IP 제한 **또는**
SSRF 차단) 이 킬체인 전체가 끊어집니다.

### 공격자 스토리라인: 왜 하필 SSH를 시도하게 되는가

이 랩의 두 결함(배스천 소스 IP 미제한, SSRF→Redis)은 공격자 입장에서 발견 순서가 다릅니다. 아무 맥락
없이 "내부 Redis를 뚫었으니 이제 SSH를 쳐보자"로 건너뛰면 부자연스럽습니다. 실제로는 이렇게 이어집니다.

1. **사전 정찰 (SSRF 발견보다 먼저)**: 공격자는 대상 조직의 공인 IP/포트를 먼저 훑습니다(nmap 등).
   이 시점에 이미 80번(쇼핑몰)과 22번(SSH) 두 포트를 발견합니다. 22번은 어떤 서버인지, 어떤 계정이
   있는지 전혀 모르고 유효한 키도 없으니 일단 "회사가 관리용 SSH를 하나 열어뒀구나" 정도로만 기록해두고,
   접근하기 쉬운 웹 앱(80)부터 공략합니다. **이 포트가 뒤에서 다시 등장한다는 게 핵심 복선입니다.**
2. **웹 앱에서 정찰**: 마이페이지의 "프로필 이미지 URL 등록"(정상 기능)을 쓰다가 응답에서
   `Via: 1.1 proxy-server.internal` 헤더를 발견합니다. "내부에 `proxy-server`라는 이름의 호스트가
   있다"는 사실과 함께, 이 이름 자체가 게이트웨이/배스천 성격을 암시합니다.
3. **SSRF로 내부 포트 확인**: 상품 이미지 자동 로딩이 SSRF라는 걸 알아채고, 방금 알아낸
   `proxy-server.internal`을 대상으로 블라인드 포트 스캔을 돌려 6379(Redis, 미인증)가 열려 있음을
   확인합니다.
4. **결정적 연결고리**: 공격자는 "내부망에서만 보이는 이 `proxy-server`가, 1단계 외부 스캔에서 이미
   봤던 그 22번 포트와 같은 물리 서버 아닐까?"라는 가설을 세웁니다 — 이름부터 프록시/게이트웨이 역할이라
   내외부 경계에 걸쳐 있는 것이 자연스럽고, 실제로 조직에서 egress 프록시와 SSH 배스천을 같은 장비에
   합쳐 운용하는 경우가 흔합니다. "그때 봐뒀지만 키가 없어 포기했던 그 SSH 포트를, 지금 손에 넣은
   Redis 미인증 접근으로 채워 넣을 수 있겠다"는 아이디어로 이어집니다.
5. **실행**: Redis가 미인증이라는 것만으로는 아직 부족합니다 — 어떤 계정으로 SSH가 열려 있는지도
   모릅니다. 그래서 `CONFIG SET dir /home/<후보 계정>/.ssh`를 계정 이름 워드리스트에 대해 반복 실행해,
   성공(`+OK`, 디렉토리 존재)/실패(`-ERR`, 없음)로 유효한 계정을 알아내는 것부터 시작합니다(Redis를
   "디렉토리 존재 여부 오라클"로 쓰는 실제 기법). 계정을 찾은 뒤 같은 방식으로 `authorized_keys`에
   공개키를 심고, 1단계에서 봐뒀던 그 SSH 포트로 돌아가 로그인합니다.

`exploit.py`도 이 순서(계정 열거 → 키 주입 → SSH 로그인)를 그대로 자동화하며, `proxyuser`라는 계정명을
스크립트에 미리 하드코딩해두지 않습니다.

## 아키텍처

```
external-net:  [attacker] ──80번 포트만──> [ec-site]
internal-net:                              [ec-site] ──Redis(6379)/Squid(3128)──> [proxy-server]
mgmt-net:      [attacker] ──SSH(22번)만, 소스 IP 제한 없음──> [proxy-server]
```

| 네트워크 | 구성원 | 역할 |
|---|---|---|
| `external-net` | attacker, ec-site | ec-site의 80번 포트만 통신 가능. host에도 `80:80`으로 노출됨 |
| `internal-net` (`172.28.99.0/24`, `internal: true`) | ec-site, proxy-server | ec-site → proxy-server의 Squid(3128)/Redis(6379). `proxy-server.internal` alias로 resolve. attacker와 host 모두 이 네트워크에 라우팅이 없고, 3128/6379는 host에도 발행(publish)되지 않음 |
| `mgmt-net` (`172.28.98.0/24`) | attacker, proxy-server | attacker ↔ proxy-server, **오직 22번(SSH)만** iptables로 허용. proxy-server 컨테이너 내부 방화벽이 이 대역에서 들어오는 나머지 포트(3128/6379 포함)를 전부 차단. proxy-server의 22번은 편의상 host에도 `22:22`로 그대로 발행되어 있음(격리 모델과 무관 — 3128/6379는 발행하지 않았으므로 Redis/Squid는 여전히 SSRF를 거쳐야만 도달 가능) |

`proxy-server`는 internal-net과 mgmt-net에만 연결되어 있고 external-net에는 라우팅이 없습니다.
`attacker`는 external-net과 mgmt-net에는 연결되어 있지만 internal-net에는 라우팅이 없어, Redis/Squid에
직접 도달할 방법이 없습니다 — 반드시 ec-site의 SSRF를 거쳐야 합니다. (`internal-net`은 Docker의
`internal: true`로 아예 라우팅 자체를 막아뒀고, `mgmt-net`은 iptables로 포트만 제한하는 구조라
`internal: true`를 걸지 않았습니다 — 그래야 22번을 host에 발행할 수 있습니다.)

## 실행 방법

```bash
docker compose up --build -d   # 빌드 + 기동
docker compose ps              # ec-site / proxy-server / attacker 모두 Up 확인
docker compose down -v         # 완전 초기화(스냅샷 리셋)
```

브라우저에서 `http://localhost` 으로 접속합니다. `python3 exploit.py`(host 실행)는 ec-site(80)와
proxy-server의 SSH(22)가 host에 발행되어 있어 별도 컨테이너 진입 없이 바로 동작합니다. `attacker`
컨테이너는 네트워크 세그멘테이션 자체를 눈으로 보여줄 때 씁니다(`docker compose exec attacker sh`) —
예를 들어 mgmt-net 안에서도 Squid/Redis 포트는 막혀 있다는 것을 확인할 때.

> host의 22번 포트를 그대로 매핑했으므로, macOS의 "원격 로그인(Remote Login)"이 이미 켜져 있다면
> 포트가 충돌합니다. 이 랩을 쓰는 동안은 시스템 설정에서 원격 로그인을 꺼두세요.

## 컨테이너 역할

| 컨테이너 | 역할 |
|---|---|
| `ec-site` | Flask 기반 쇼핑몰(일본어 UI, 엔화(¥) 표시). 회원가입/로그인, 상품 목록·카테고리(6개, 약 30개 상품), 장바구니, 간이 결제, 그리고 아래 취약점들을 포함 |
| `proxy-server` | Ubuntu 기반. Squid(정상 egress 프록시) + Redis(미인증, 비-root 계정으로 실행) + OpenSSH 배스천(`proxyuser`) + iptables(mgmt-net 소스에서 22번 외 전부 차단) |
| `attacker` | curl/openssh-client/python3/redis-tools를 담은 공격자 시점 컨테이너. external-net과 mgmt-net에만 연결됨 |

## 취약점 설명

### 1. Via 헤더 노출 (정찰) — 마이페이지 프로필 이미지 등록

`POST /profile/image-preview`는 사용자가 프로필 이미지 URL을 등록하는 **정상 기능**입니다. 사내 egress
정책에 따라 이 요청은 반드시 Squid(`proxy-server.internal:3128`)를 forward proxy로 경유하도록
구현되어 있습니다. Squid는 표준 동작으로 응답에 `Via: 1.1 proxy-server.internal (squid/x.x)` 헤더를
붙이는데, ec-site가 이 헤더를 제거하지 않고 그대로 클라이언트에 전달합니다. 이 정상 기능을 한 번
사용해보는 것만으로 공격자는 내부 호스트명(`proxy-server.internal`)을 알아냅니다. `http://`,
`https://` 대상 모두 동일하게 헤더가 붙습니다 — HTTPS는 Squid가 CONNECT 터널만 통과시킬 뿐 내용을
볼 수 없어 자체적으로는 Via를 못 붙이지만, ec-site가 그 경우엔 같은 형식의 헤더를 직접 채워 넣어서
유출이 스킴에 따라 갈리지 않도록 했습니다.

- **왜 위험한가**: "사내 정책을 지켜 프록시를 거치게 했다"는 조치가 오히려 내부 인프라 정보를 외부에
  흘려보내는 통로가 됩니다. 정상 기능이라 로그 상으로도 의심스럽지 않습니다.
- **올바른 운영 설정**: 응답이 최종 사용자에게 도달하기 전에 `Via`, `X-Powered-By`, `Server` 등 내부
  정보를 드러내는 헤더를 제거해야 합니다 (Squid의 경우 `via off`).

### 2. Squid의 느슨한 ACL

`squid.conf`는 목적지 IP/포트 제한 없이 `http_access allow all`로 설정되어 있습니다.

- **왜 위험한가**: 포워드 프록시가 목적지를 제한하지 않으면 "프록시를 거치니 안전하다"는 가정 자체가
  무의미해지고, 내부망 스캐닝/피벗의 발판이 될 수 있습니다.
- **올바른 운영 설정**: 목적지 포트를 `Safe_ports`(80, 443 등)로 제한하고, 목적지 IP 대역에 대한
  allowlist ACL을 적용해야 합니다.

### 3. SSRF — 상품 이미지 자동 로딩 (목적지 미검증 + Squid 미경유)

상품 목록/상세 페이지의 상품 이미지는 `GET /product/image?url=...`로 서버가 대신 가져와 응답하는
방식으로 자동 로드됩니다. 이 엔드포인트는 **Squid를 거치지 않고 목적지에 직접 연결**하도록 구현되어
있습니다 (1번 기능과 대비되는 아웃바운드 처리 비일관성 — 개발자가 "이미지 로딩은 가벼운 기능이니
프록시를 안 거쳐도 된다"고 판단한 흔한 실수). 목적지 검증(allowlist/블랙리스트)이 전혀 없고
리다이렉트도 그대로 따라갑니다(`allow_redirects=True`).

포트가 열려있는지/닫혀있는지/필터링되는지에 따라 응답 코드와 응답 시간이 다르게 나타나 블라인드
포트 스캔이 가능합니다. 또한 `gopher://` 스킴은 `requests`가 지원하지 않아 별도의 raw 소켓 분기
(`_fetch_gopher`)로 처리되며, 이 경로로 Redis RESP 프로토콜 명령을 스머글링할 수 있습니다.

- **왜 위험한가**: "이미지 프록시" 같은 지극히 정상적으로 보이는 기능이 인증도 검증도 없이 서버가 임의
  URL로 아웃바운드 요청을 수행하는 통로입니다. SSRF는 내부망 전체를 공격 표면으로 바꿔버립니다.
- **올바른 운영 설정**: 모든 서버-사이드 아웃바운드 요청은 목적지 allowlist·사설 IP 대역 차단·리다이렉트
  목적지 재검증을 예외 없이 적용해야 하며, 같은 애플리케이션 안의 아웃바운드 처리 경로가 기능마다
  달라서는 안 됩니다.

### 4. Redis 미인증 접근 (비-root로 실행되지만 여전히 위험)

`proxy-server`의 Redis는 `requirepass` 없이 실행되며 internal-net 전체에서 미인증 접근이 가능합니다.
**Redis 자체는 저권한 전용 시스템 계정(`redisuser`)으로 실행되어 root 권한이 전혀 없습니다** — 그럼에도
Redis가 파일을 쓸 수 있는 디렉토리가 잘못 설정되어 있다면(→ 취약점 5) 그것만으로 충분히 위험합니다.

- **왜 위험한가**: 미인증 데이터스토어는 그 자체로 정보 유출/조작 위험이며, "root가 아니니 안전하다"는
  가정은 그 계정이 쓸 수 있는 경로가 무엇인지에 따라 완전히 무너질 수 있습니다.
- **올바른 운영 설정**: `requirepass`(또는 ACL) 설정, `protected-mode yes`, 바인드 인터페이스 최소화,
  그리고 Redis를 신뢰할 수 없는 네트워크에서 도달 가능하게 두지 않는 것(방화벽/네트워크 세그멘테이션).

### 5. SSH 홈디렉토리 권한 오설정 (그룹 쓰기 권한 실수)

`proxyuser`의 `/home/proxyuser/.ssh` 디렉토리가 `redisuser`와 같은 그룹(`redisgrp`) 소유로 설정되어
있고, 그룹 쓰기 권한(`2775`)이 부여되어 있습니다. 이는 "같은 그룹이니 괜찮겠지"라는 흔한 실수로, Redis
실행 계정이 SSH 인증에 쓰이는 디렉토리에 파일을 쓸 수 있게 만듭니다. 또한 `sshd_config`에
`StrictModes no`가 설정되어 있어, OpenSSH 자체의 기본 보호 기능(그룹 쓰기 가능한 `authorized_keys`를
거부하는 것)마저 꺼져 있습니다.

- **왜 위험한가**: SSH 키 기반 인증은 "개인키가 없으면 안전하다"는 신뢰 모델인데, 인증에 사용되는
  `authorized_keys` 파일 자체를 다른(더 낮은 권한의) 계정이 쓸 수 있다면 그 신뢰 모델이 완전히
  무너집니다.
- **올바른 운영 설정**: `~/.ssh`와 `authorized_keys`는 소유자만 쓸 수 있어야 하며(`700`/`600`), 다른
  서비스 계정과 그룹을 공유해서는 안 됩니다. `StrictModes yes`(기본값)를 유지하면 OpenSSH가 이런
  오설정을 자동으로 거부합니다.

### 6. mgmt-net 소스 IP 미제한 (배스천 오설정)

`proxy-server`는 mgmt-net에서 들어오는 트래픽 중 iptables로 22번 포트만 허용하고 나머지는 전부
차단합니다. 이 자체는 정상적인 배스천 아키텍처이지만, **22번 포트 자체에는 소스 IP 제한이 전혀
없습니다** — mgmt-net에 있는 누구든 SSH 포트까지는 도달할 수 있습니다.

- **왜 위험한가**: "관리 포트만 열어뒀으니 안전하다"는 가정은 그 포트에 접근할 수 있는 대상을 제한하지
  않으면 인증 우회/키 탈취가 일어났을 때 곧바로 침투로 이어집니다.
- **올바른 운영 설정**: 관리 포트는 알려진 관리자/점프서버 IP 대역으로만 접근을 제한해야 하며(방화벽
  allowlist, VPN 경유 등), "포트가 적다"는 것과 "접근 가능한 대상이 적다"는 것은 별개입니다.

### 7. sudo NOPASSWD 권한상승 (GTFOBins)

`proxyuser`는 `sudo -l`로 확인 가능한 `NOPASSWD: /usr/bin/python3` 항목을 갖고 있습니다
(`/etc/sudoers.d/proxy-lab-privesc`). GTFOBins에 등재된 전형적인 패턴으로 `sudo python3 -c
'import os; os.system("/bin/bash")'` 한 줄로 root 셸을 얻습니다. 이 벡터는 별도 파일로 분리되어
있어 다른 벡터(크론잡, SUID 바이너리, 커널 CVE 등)로 쉽게 교체할 수 있습니다.

- **왜 위험한가**: NOPASSWD sudo 항목은 해당 계정이 탈취되는 순간 곧바로 root 권한 상승으로 이어집니다.
- **올바른 운영 설정**: sudo 권한은 최소 권한 원칙에 따라 꼭 필요한 명령으로 제한하고, GTFOBins에
  등재된 범용 인터프리터/에디터에는 NOPASSWD를 부여하지 않아야 합니다.

## 공격 시나리오 검증 절차

전체 절차는 `DEMO.md`에 화면 시연 스크립트로 정리되어 있습니다. 요약:

1. (사전 정찰) `nmap`으로 외부에서 22번(SSH)이 열려 있는 것을 확인해두지만, 계정도 키도 없어 보류
2. 회원가입 → 로그인 → `/profile/image-preview`에 URL 등록 → 응답의 `Via: 1.1
   proxy-server.internal` 확인 (정찰)
3. `/product/image?url=http://proxy-server.internal:<port>`로 블라인드 포트 스캔 → `:6379`에서
   "port open, non-http response" 확인
4. gopher 스킴으로 Redis에 `CONFIG SET dir /home/<후보>/.ssh`를 계정명 워드리스트로 반복 실행해
   유효한 계정을 열거(`+OK`/`-ERR`로 판별)
5. 찾은 계정으로 `CONFIG SET dir` → `CONFIG SET dbfilename authorized_keys` →
   `SET payload "<attacker 공개키>"` → `SAVE` 전송
6. host에서 `ssh -p 22 -i <주입한 개인키> <찾은 계정>@localhost` → 1단계에서 봐뒀던 그 포트로 로그인 성공
7. `sudo -l` → `NOPASSWD: /usr/bin/python3` 확인 → `sudo python3 -c 'import os; os.system("id")'`로
   root 셸 획득

`exploit.py`는 3~7단계(계정 열거 → 키 주입 → SSH 로그인 → 권한상승 확인)를 자동화한 PoC
스크립트로, host에서 바로 실행합니다 (repo 루트에서):

```bash
python3 exploit.py
```

## 구현 노트

- `app.py`의 `/product/image`는 `gopher://` 스킴일 때만 raw 소켓으로 직접 페이로드를 전송하는 별도
  분기(`_fetch_gopher`)를 갖습니다. `requests` 라이브러리가 gopher 스킴을 지원하지 않기 때문에
  필요한 최소한의 배관이며, 공격자↔Redis 사이의 유일한 경로이므로 제거하지 마세요.
- `/product/image`의 비-gopher 분기는 Squid를 거치지 않으므로, 열림/닫힘/필터링 구분을 `requests`
  예외로 직접 판별합니다: `Timeout` → 필터링(504), `ConnectionRefusedError`가 원인인
  `ConnectionError` → 닫힘(502), 그 외 `ConnectionError`(bad status line 등) → 열렸지만 비-HTTP
  응답(200).
- Ubuntu의 `redis-server` 패키지는 `/etc/redis`를 자체 `redis` 시스템 계정 전용으로 잠가두므로,
  이 랩의 별도 `redisuser` 계정이 설정 파일을 읽을 수 있도록 Dockerfile에서 권한을 조정했습니다.
- `sshd_config`에 `StrictModes no`가 명시적으로 필요합니다 — 그렇지 않으면 OpenSSH 자체가 그룹
  쓰기 가능한 `.ssh`/`authorized_keys`를 거부해 이 랩이 재현하려는 취약점이 애초에 성립하지 않습니다.
  (`Authentication refused: bad ownership or modes for file ...`)
- iptables 규칙은 mgmt-net의 서브넷(`172.28.98.0/24`)을 소스로 매칭해 22번 외 포트를 차단합니다.
  인터페이스 이름 대신 소스 IP 대역으로 매칭하므로 네트워크 연결 순서와 무관하게 동작합니다.
- `exploit.py`는 SSH 계정명(`proxyuser`)을 하드코딩하지 않습니다. `CONFIG SET dir <path>`는 `<path>`가
  실제로 존재해야만 `+OK`를 반환하고 없으면 `-ERR`을 반환하는 Redis의 정상 동작인데, 이를
  `/home/<후보 계정>/.ssh`에 대해 워드리스트로 반복하면 미인증 Redis를 "그 계정이 이 서버에 존재하는지"
  알려주는 오라클로 쓸 수 있습니다 — 공격자가 대상 서버의 계정 체계를 사전에 알 필요가 없습니다.
- proxy-server의 SSH(22)를 host에도 그대로 발행했으므로, macOS의 원격 로그인(시스템 설정 →
  일반 → 공유 → 원격 로그인)이 켜져 있으면 포트 충돌이 납니다. 랩을 쓰는 동안은 꺼두세요.
