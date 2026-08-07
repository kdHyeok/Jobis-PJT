# ops 작업자 진입점 (Infra 소유)

@AGENTS.md

루트 [../AGENTS.md](../AGENTS.md)가 상위 규약이고, 배포 절차는 [DEPLOYMENT.md](DEPLOYMENT.md)가 정본이다.

여기와 루트 `Jenkinsfile`, `infra/`, `compose.yaml`은 CI/CD 뼈대다. 기능 개발자가 자기 기능을
통과시키려고 단독으로 바꾸지 않는다 — MR + Infra 리뷰(`.gitlab/CODEOWNERS`).

깨뜨리면 안 되는 불변식은 `AGENTS.md`의 "바꾸지 말아야 할 불변식"에 있다.
