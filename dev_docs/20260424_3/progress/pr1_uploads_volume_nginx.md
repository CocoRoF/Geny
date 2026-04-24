# PR-1 Progress — Uploads volume + nginx `/static/uploads/`

**Branch:** `chore/20260424_3-pr1-uploads-volume-nginx`
**Base:** `main @ e168932`

## Changes

### docker-compose — named volume 추가
- `docker-compose.yml` — `geny-uploads:/app/static/uploads` mount + 루트 `volumes:` 에 선언
- `docker-compose.prod.yml` — `geny-uploads-prod:/app/static/uploads`
- `docker-compose.prod-core.yml` — 동일 prod suffix

Dev 파일들 (`docker-compose.dev.yml`, `docker-compose.dev-core.yml`) 은 `./backend:/app` 전체 bind mount 를 쓰므로 호스트 디렉토리에 자동 영속. 별도 변경 없음.

### nginx — `/static/uploads/` location 추가
- `nginx/nginx.conf` — 기존 `/static/assets/`, `/static/live2d-models/` 와 같은 패턴으로 backend 로 proxy. 콘텐츠-어드레스 (sha256) 이므로 `immutable` cache-control + 1d 캐시.

## Rationale

- 업로드는 `/app/static/uploads/{sha256[:2]}/{sha256}.{ext}` (content-addressable) 로 저장되지만 volume 없어 컨테이너 재시작마다 소실
- Nginx 에 명시 location 없으면 `/static/uploads/` 요청이 마지막 `location /` → frontend 로 프록시돼 404
- 두 가지가 함께 작동할 때만 "업로드 → 저장 → 서빙" 전체 경로 성립

## Verification (배포 후 리뷰어)

```bash
$ docker compose up -d --force-recreate backend nginx
$ curl -F files=@test.png http://localhost/api/uploads
{"files":[{"kind":"image","url":"/static/uploads/ab/ab...png", ...}]}

$ curl -I http://localhost/static/uploads/ab/ab...png
HTTP/1.1 200 OK
Cache-Control: public, max-age=86400, immutable

$ docker compose restart backend
$ curl -I http://localhost/static/uploads/ab/ab...png
HTTP/1.1 200 OK   # still served after restart
```

## Risk / Migration

- 기존 컨테이너에 남아있던 업로드가 있다면 named volume 마운트 시 mask. 현재 프로덕션은 "재시작마다 사라지던" 상태라 실질적 손실 없음.
- 롤백은 `git revert` + 필요 시 `docker volume rm geny-uploads(-prod)`.

## Next

PR-2: chat_controller 의 `_rewrite_local_attachment_url` 이 실제 파일 존재 여부 검증하도록 + executor 의 silent drop 을 warning → error 로 surface.
