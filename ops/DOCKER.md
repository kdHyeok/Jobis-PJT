# JOBISS Docker 운영 정본

활성 배포 이미지는 `jobis-ai`, `jobis-backend`, `jobis-frontend` 세 개다. 배포 서버가
Jenkins와 다른 Docker daemon이면 `JOBIS_IMAGE_PREFIX`가 가리키는 registry를 통해 불변
커밋 SHA 태그를 전달한다.

PostgreSQL은 첫 전환에서 호스트에 유지하고 logical dump로 보호한다. DB 컨테이너 이미지와
Docker volume 자체는 백업이 아니다. 전체 설치, registry, 배포, 백업, 복원, 롤백 절차는
[DEPLOYMENT.md](DEPLOYMENT.md)를 따른다.

`fake-ai`, 별도 `ai-server`, jar/systemd 배포는 활성 경로가 아니다. 기존 systemd unit은
첫 전환의 비상 후퇴용으로만 잠시 보존하고, 두 번의 정상 컨테이너 릴리스와 이미지 롤백
훈련을 확인한 뒤 서버에서 제거한다.
