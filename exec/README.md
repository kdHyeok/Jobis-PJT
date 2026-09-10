# JOBIS 포팅 매뉴얼

이 폴더는 GitLab 소스를 클론한 사람이 빌드·배포·시연까지 재현할 수 있도록 정리한 문서다.
소스코드는 저장소 본체에 있으므로 여기에 다시 올리지 않는다.

| 파일 | 내용 |
|---|---|
| [1-build-and-deploy.md](1-build-and-deploy.md) | 사용 제품·버전, 환경 변수, 배포 특이사항, 계정·프로퍼티 파일 목록 |
| [2-external-services.md](2-external-services.md) | 외부 서비스 가입·발급·설정 정보 |
| [4-demo-scenario.md](4-demo-scenario.md) | 시연 순서에 따른 화면별·클릭별 상세 설명 |

## 가장 빠른 재현

```powershell
git clone https://lab.ssafy.com/s15-webmobile1-sub1/S15P11C202.git
cd S15P11C202
Copy-Item .env.compose-local.example .env
# .env 의 비밀값과 LLM_PROVIDER 키를 채운다 (1-build-and-deploy.md 3장)
docker compose up --build -d
```

`http://localhost:8088` 이 열리면 성공이다. 자세한 검증 절차는
[1-build-and-deploy.md](1-build-and-deploy.md) 5장에 있다.
