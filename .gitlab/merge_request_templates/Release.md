<!-- Source: develop / Target: master -->

## 릴리스 범위

- 릴리스 커밋 또는 이슈:
- 사용자 영향:
- API 계약 변경:
- DB/Flyway 변경:
- 추가·변경 환경 변수:

## 승격 전 확인

- [ ] Source Branch가 `develop`, Target Branch가 `master`이다.
- [ ] `develop`의 최신 Jenkins 파이프라인이 모두 성공했다.
- [ ] `Backend`, `AI v2bridge`, `Frontend`, `RAG`, `Infra` 검증 결과를 확인했다.
- [ ] `jobis-ai`, `jobis-backend`, `jobis-frontend` 세 이미지 빌드가 성공했다.
- [ ] 운영 환경 변수 이름을 확인했으며 비밀값은 MR·로그에 기록하지 않았다.
- [ ] DB/Flyway 변경의 이전·이후 호환성과 롤백 제약을 검토했다.
- [ ] 배포 서버의 디스크, Docker daemon, Compose, Nginx 상태를 확인했다.
- [ ] 최근 DB 백업과 격리 복원 테스트가 성공했다.
- [ ] 운영 배포 중인 다른 Jenkins 작업이 없다.

## 배포·검증 계획

1. `master` 병합 후 생성되는 불변 SHA 이미지 3개를 확인한다.
2. CD 직전 생성된 DB dump, checksum, manifest 경로를 기록한다.
3. AI `/health`, backend `/api/health`, frontend `/`, `/api/auth/csrf`를 확인한다.
4. 외부 HTTPS 경로에서 로그인과 핵심 사용자 흐름을 smoke test한다.

## 롤백 계획

- 이전 정상 SHA:
- 애플리케이션 롤백 명령: `sudo /usr/local/sbin/deploy-jobis <이전-SHA>`
- DB 복원이 필요한 조건과 승인자:
- 장애 시 연락·공유 경로:

> DB 복원은 애플리케이션 롤백과 별도 작업이다. 데이터 손실 가능성을 검토하고 명시적으로 승인한 경우에만 수행한다.

## 배포 후 기록

- Jenkins 배포 작업 URL:
- 배포 SHA:
- DB 백업 파일과 checksum:
- smoke test 결과:
- 관찰된 경고 또는 후속 작업:
