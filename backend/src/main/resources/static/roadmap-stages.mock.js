/* ============================================================
   roadmap-stages.mock.js — "학습 모듈 → 결과물 → 시험" 단계형 로드맵 목업의
   fixture + mock service. (실제 API 없음 — 교체 지점을 주석으로 표기)

   콘텐츠 출처: 기획 목업(roadmap-stages-test1)의 10단계 커리큘럼을 이식하고,
   ①공고 근거 배지(이스트게임즈 원문 인용) ②진단 기반 건너뜀 ③검수 출처 3종
   ④서술형 시험 문항을 추가함. 예제 코드의 실명은 익명화.

   교체 계획(백엔드 연동 시):
   - RSMock.load(...)         → GET  /api/roadmap-stages?analysisId=&routeId=
   - completeLesson/markExternalDone → POST /api/roadmap-stages/{no}/lessons/{i}
   - submitArtifact()         → POST /api/roadmaps/reassess (기존 계약 확장)
   - startTest/submitTest/retryTest  → POST /api/roadmap-stages/{no}/test
   - nextStage()              → POST /api/roadmap-stages/{no}/advance
   상태 매핑: ArtifactStatus.PASSED ≈ RoadmapStepStatus.VERIFIED /
             REVISION_REQUIRED ≈ NEEDS_WORK. reviews[] ≈ verdict_json.checks[] 확장.
   ============================================================ */
(function () {
  'use strict';

  var GOAL = {
    posting: '[ESTgames] 웹 개발자',
    track: 'Java/Spring 백엔드 중심',
    project: 'GameHub',
    projectDesc: '게임 이벤트·보상·포인트·아이템 구매를 연결한 웹 서비스',
    userState: '진단 결과: 기초 회복 필요 — 배운 지식은 있으나 독립 구현 능력을 다시 활성화해야 하는 상태'
  };

  /* 단계 데이터 — evidence = 공고 근거 배지 {type: 필수|우대|담당업무|제출요건, quote: 원문 인용} */
  var STAGES = [
    { no: 0, title: '개발 환경과 컴퓨터 기초',
      goal: '프로그램과 소스 코드의 차이를 이해하고 Java 프로그램을 직접 실행합니다.',
      why: '개발 경험이 전혀 없다면 파일·실행·개발 도구와 Git의 역할부터 이해해야 이후 단계에서 길을 잃지 않습니다.',
      evidence: { type: '필수', quote: 'Git 등 버전 관리 시스템 사용 경험이 있는 분' },
      skipNote: '진단에서 IDE 실행 경험과 Git 작업 흐름 이해가 확인되어 이 단계는 건너뜁니다.',
      lessons: [['파일과 경로','파일·폴더·확장자와 경로가 무엇인지 배웁니다.'],['소스 코드와 실행','작성한 코드가 프로그램으로 실행되는 과정을 확인합니다.'],['IDE와 터미널','코드를 작성하는 도구와 명령을 실행하는 도구를 구분합니다.'],['Git과 커밋','코드의 변경 내용을 기록하고 되돌릴 수 있게 관리합니다.']],
      practice: ['Java 파일을 만들고 문구 출력하기','출력 문구를 수정하고 다시 실행하기','Git 저장소를 만들고 첫 커밋 남기기'],
      artifact: ['HelloGame 프로그램','플레이어 이름과 초기 포인트를 출력하는 첫 Java 프로그램'],
      criteria: ['Java 파일을 직접 생성한다.','프로그램을 실행하고 출력 문구를 변경한다.','오류가 발생한 위치를 확인한다.','Git 저장소를 만들고 첫 커밋을 남긴다.'],
      questions: [['소스 코드에 대한 설명으로 맞는 것은?',['컴파일 결과로 만들어진 실행 파일','프로그램을 만들기 위해 사람이 작성한 명령과 문장','실행되는 동안 메모리에 올라간 프로세스'],1],['IDE의 주된 역할은 무엇인가요?',['코드 작성·실행·디버깅을 한 곳에서 돕는다','작성한 코드를 서버에 자동으로 배포한다','코드를 실행 파일로 바꾸는 컴파일러 그 자체다'],0],['Git 커밋(commit)의 목적은 무엇인가요?',['원격 저장소에 코드를 업로드한다','변경 내용을 의미 있는 단위로 기록해 되돌릴 수 있게 한다','작업 폴더의 파일을 주기적으로 자동 백업한다'],1]],
      next: ['변수와 자료형','조건문','반복문','메서드'] },

    { no: 1, title: 'Java 프로그래밍 기초',
      goal: '조건과 반복을 사용해 간단한 게임 규칙을 구현합니다.',
      why: 'Spring도 결국 Java 코드로 동작합니다. 변수·조건문·반복문·메서드를 직접 사용할 수 있어야 웹 기능을 구현할 수 있습니다.',
      evidence: { type: '필수', quote: '하나 이상의 General-purpose 프로그래밍 언어로 소프트웨어를 개발한 경험이 있는 분' },
      lessons: [['변수와 자료형','문자와 숫자를 프로그램에 저장합니다.'],['조건문','구매 가능 여부처럼 상황에 따라 다르게 처리합니다.'],['반복문','여러 아이템을 같은 규칙으로 처리합니다.'],['메서드','계산과 검사를 재사용 가능한 기능으로 분리합니다.']],
      practice: ['포인트와 가격 비교하기','여러 아이템 가격 합산하기','구매 후 잔액 계산하기'],
      artifact: ['GamePointCalculator','포인트와 아이템 가격을 계산하는 Java 콘솔 프로그램'],
      criteria: ['변수에 포인트와 가격을 저장한다.','잔액 부족 시 구매를 거절한다.','반복문으로 여러 아이템을 처리한다.','계산 기능을 메서드로 분리한다.'],
      questions: [['if문이 꼭 필요한 상황은 무엇인가요?',['잔액이 가격보다 적을 때만 구매를 거절해야 할 때','여러 아이템에 같은 계산을 반복해야 할 때','같은 검사를 여러 곳에서 재사용해야 할 때'],0],['반복문이 가장 적합한 경우는 무엇인가요?',['잔액이 부족한지 한 번만 확인할 때','장바구니의 아이템 가격을 하나씩 모두 더할 때','계산 결과를 화면에 한 번 출력할 때'],1],['계산을 메서드로 분리하는 가장 큰 이유는 무엇인가요?',['실행 속도가 항상 빨라져서','코드 줄 수가 무조건 줄어들어서','같은 검사·계산을 재사용하고 역할을 나눌 수 있어서'],2]],
      next: ['클래스와 객체','캡슐화','List·Map','예외 처리'] },

    { no: 2, title: '객체지향과 컬렉션',
      goal: '게임 데이터를 클래스로 표현하고 여러 아이템을 관리합니다.',
      why: '백엔드에서는 회원·지갑·아이템 같은 대상을 객체로 표현합니다. 안전한 상태 변경과 컬렉션 사용은 이후 도메인 설계의 기반입니다.',
      evidence: { type: '필수', quote: 'CS(Computer Science) 기본 지식을 갖춘 분 (자료구조, 알고리즘, 네트워크 등)' },
      files: ['Wallet.java','Item.java','Main.java','README.md'],
      lessons: [['클래스와 객체','데이터와 행동을 하나의 역할로 묶습니다.'],['캡슐화','외부에서 잘못된 상태를 만들지 못하게 제한합니다.'],['컬렉션','List·Set·Map으로 여러 데이터를 관리합니다.'],['예외 처리','잘못된 요청이 들어왔을 때 안전하게 실패합니다.']],
      practice: ['Wallet의 충전·사용 메서드 만들기','Map으로 아이템 개수 세기','잔액 부족 상황 처리하기'],
      artifact: ['GameWallet','포인트와 아이템 보유 수량을 관리하는 콘솔 프로그램'],
      criteria: ['포인트를 외부에서 직접 변경할 수 없다.','charge()와 spend()로 상태를 변경한다.','Map으로 아이템 수량을 관리한다.','음수 금액과 잔액 부족을 처리한다.'],
      questions: [['필드를 private으로 두는 이유는 무엇인가요?',['외부에서 검증 없이 값을 바꾸는 것을 막기 위해','메모리 사용량을 줄이기 위해','클래스 상속을 가능하게 하기 위해'],0],['Map이 가장 적합한 상황은 무엇인가요?',['아이템을 담은 순서 그대로 꺼내야 할 때','아이템 이름으로 보유 수량을 바로 찾아야 할 때','중복 없이 값의 존재 여부만 관리할 때'],1],['setBalance() 대신 charge()/spend()를 두는 이유는 무엇인가요?',['금액 검증과 잔액 확인 규칙을 메서드 안에서 강제할 수 있어서','메서드가 많을수록 객체지향적이라서','private 필드에는 setter를 만들 수 없어서'],0]],
      next: ['HTML','CSS','JavaScript','HTTP·JSON'] },

    { no: 3, title: '웹과 프론트엔드 기초',
      goal: '브라우저에서 동작하는 간단한 게임 이벤트 화면을 만듭니다.',
      why: '백엔드 개발자도 브라우저가 서버에 어떻게 요청하고 응답을 화면에 어떻게 표시하는지 이해해야 API를 올바르게 설계할 수 있습니다.',
      evidence: { type: '필수', quote: '웹 프론트엔드 및 백엔드 개발의 기본 지식 · W3C 웹 표준에 대한 이해가 있는 분' },
      lessons: [['HTML','화면의 정보 구조를 만듭니다.'],['CSS','레이아웃과 정보의 우선순위를 표현합니다.'],['JavaScript','버튼과 화면 상태를 동작시킵니다.'],['HTTP와 JSON','브라우저와 서버가 데이터를 주고받습니다.']],
      practice: ['이벤트 카드 만들기','버튼 클릭 상태 변경하기','JSON 목록을 화면에 표시하기'],
      artifact: ['게임 이벤트 안내 페이지','이벤트 목록과 보상 정보를 보여주는 정적 웹 페이지'],
      criteria: ['HTML로 정보 구조를 작성한다.','CSS로 내용을 읽기 쉽게 구성한다.','버튼 클릭을 JavaScript로 처리한다.','JSON 데이터를 화면에 표시한다.'],
      questions: [['HTML의 역할은 무엇인가요?',['화면의 배치와 색을 지정한다','버튼 클릭 같은 동작을 처리한다','화면에 표시할 정보의 구조를 작성한다'],2],['GET 요청이 적합한 경우는 무엇인가요?',['이벤트 목록을 조회할 때','새 회원 정보를 등록할 때','비밀번호를 변경할 때'],0],['JSON을 사용하는 이유는 무엇인가요?',['자바 객체를 브라우저에서 직접 실행하기 위해','구조화된 데이터를 언어와 무관하게 주고받기 위해','HTML 대신 화면을 그리기 위해'],1]],
      next: ['테이블','기본키·외래키','CRUD','JOIN'] },

    { no: 4, title: '데이터베이스와 SQL',
      goal: '회원·이벤트·구매 정보를 데이터베이스에 저장하고 조회합니다.',
      why: '게임 웹 서비스의 회원·구매·보상 기록은 서버가 종료되어도 유지돼야 하므로 관계형 데이터베이스와 SQL이 필요합니다.',
      evidence: { type: '필수', quote: 'Database 관련 기본 지식을 갖춘 분 (개발환경: MSSQL, MySQL)' },
      lessons: [['테이블과 관계','데이터를 행과 열로 구조화합니다.'],['기본키·외래키','데이터를 식별하고 테이블을 연결합니다.'],['CRUD','데이터를 추가·조회·수정·삭제합니다.'],['JOIN과 집계','여러 테이블을 연결하고 통계를 계산합니다.']],
      practice: ['회원과 구매 테이블 설계하기','완료 구매만 조회하기','사용자별 구매액 집계하기'],
      artifact: ['GameHub 데이터베이스','회원·이벤트·아이템·구매 테이블과 핵심 SQL'],
      criteria: ['기본키와 외래키를 지정한다.','CRUD SQL을 작성한다.','회원과 구매 내역을 JOIN한다.','사용자별 총구매 금액을 계산한다.'],
      questions: [['기본키의 역할은 무엇인가요?',['각 행을 고유하게 식별한다','두 테이블의 데이터를 합쳐서 조회한다','조회 조건에 맞는 행만 골라낸다'],0],['JOIN이 필요한 경우는 무엇인가요?',['한 테이블에서 조건에 맞는 행만 고를 때','회원 이름과 그 회원의 구매 내역을 함께 조회할 때','테이블의 열 이름을 바꿀 때'],1],['WHERE와 HAVING의 차이는 무엇인가요?',['HAVING은 GROUP BY 집계 결과에 조건을 건다','HAVING이 WHERE보다 항상 먼저 실행된다','둘은 완전히 같아서 아무거나 써도 된다'],0]],
      next: ['Git 브랜치','자료구조','DNS·TCP','HTTP 요청 흐름'] },

    { no: 5, title: 'Git·CS 기초',
      goal: '코드를 안전하게 관리하고 웹 서비스가 동작하는 기본 원리를 이해합니다.',
      why: '회사는 코드를 혼자 작성하는 곳이 아닙니다. 변경 이력 관리와 네트워크·자료구조의 기본 원리를 이해해야 협업과 문제 해결이 가능합니다.',
      evidence: { type: '필수', quote: 'Git 등 버전 관리 시스템 사용 경험 · CS 기본 지식(자료구조, 네트워크)' },
      lessons: [['Git 브랜치','기능별 변경을 분리하고 병합합니다.'],['자료구조','데이터 특성에 맞는 구조를 선택합니다.'],['프로세스와 메모리','프로그램이 실행되는 기본 원리를 이해합니다.'],['네트워크','DNS·TCP·HTTP 요청 흐름을 확인합니다.']],
      practice: ['기능 브랜치 만들기','충돌 해결 후 테스트하기','브라우저 요청 흐름 설명하기'],
      artifact: ['협업 기초 기록','브랜치·커밋 기록과 웹 요청 흐름 설명 문서'],
      criteria: ['기능별 브랜치를 사용한다.','충돌을 해결하고 테스트한다.','List·Set·Map을 구분한다.','브라우저 요청 흐름을 설명한다.'],
      questions: [['브랜치를 사용하는 이유는 무엇인가요?',['커밋 기록을 삭제하기 위해','원격 저장소에 코드를 업로드하기 위해','기능 작업을 분리해 main에 영향 없이 진행하고 병합하기 위해'],2],['DNS의 역할은 무엇인가요?',['도메인 이름을 IP 주소로 변환한다','주고받는 데이터를 암호화한다','손실된 패킷을 다시 보내준다'],0],['Set이 가장 적합한 상황은 무엇인가요?',['보상을 이미 받은 사용자 ID를 중복 없이 관리할 때','사용자 이름으로 잔액을 바로 찾아야 할 때','요청을 도착한 순서대로 처리해야 할 때'],0]],
      next: ['Controller','Service','Repository','JPA·REST'] },

    { no: 6, title: 'Spring Boot REST API',
      goal: 'Java로 웹 서버를 만들고 MySQL과 연결합니다.',
      why: '목표 공고가 요구하는 Java/Spring 백엔드 역량을 실제 API 결과물로 전환하는 핵심 단계입니다.',
      evidence: { type: '우대', quote: 'HTTP API 클라이언트 및 백엔드의 REST API 또는 GraphQL 개발 및 설계가 가능한 분 (개발환경: Spring Boot)' },
      lessons: [['Spring 계층','Controller·Service·Repository 역할을 나눕니다.'],['REST API','URL·메서드·상태 코드로 기능을 설계합니다.'],['JPA','Java 객체와 데이터베이스를 연결합니다.'],['예외 처리','오류를 일관된 API 응답으로 반환합니다.']],
      practice: ['이벤트 조회 API 만들기','MySQL에 이벤트 저장하기','404 오류 응답 만들기'],
      artifact: ['게임 이벤트 REST API','이벤트 CRUD와 MySQL 연동이 가능한 Spring Boot 서버'],
      criteria: ['프로젝트를 직접 생성한다.','계층별 역할을 구분한다.','Entity와 DTO를 구분한다.','오류에 맞는 HTTP 상태를 반환한다.'],
      questions: [['Controller의 역할은 무엇인가요?',['비즈니스 규칙을 계산하는 계층이다','HTTP 요청을 받아 응답을 돌려주는 창구다','DB에 쿼리를 직접 보내는 계층이다'],1],['Entity와 별도로 DTO를 두는 이유는 무엇인가요?',['API 응답 형태를 DB 구조와 분리해 계약을 지키기 위해','클래스 수가 많을수록 성능이 좋아져서','JPA가 DTO 없이는 동작하지 않아서'],0],['404 상태 코드가 맞는 상황은 무엇인가요?',['로그인이 필요한데 토큰이 없을 때','서버 코드에서 예외가 발생했을 때','요청한 이벤트 ID가 존재하지 않을 때'],2]],
      next: ['회원·권한','이벤트 보상','포인트 원장','아이템 구매'] },

    { no: 7, title: 'GameHub 핵심 기능',
      goal: '게임 이벤트·보상·아이템 상점의 핵심 사용자 흐름을 구현합니다.',
      why: '공고의 게임 이벤트·플랫폼·과금 서비스 업무와 직접 연결되는 대표 포트폴리오 결과물을 만드는 단계입니다.',
      evidence: { type: '담당업무', quote: '게임 내 결제 시스템 및 과금 서비스 개발 · 게임 관련 웹 서비스 개발(게임 포털, 커뮤니티, 이벤트 페이지 등)' },
      lessons: [['인증·인가','로그인과 역할별 접근을 구분합니다.'],['이벤트 보상','사용자당 한 번만 보상을 지급합니다.'],['포인트 원장','충전·사용 이력을 기록합니다.'],['구매와 인벤토리','차감과 아이템 지급을 연결합니다.']],
      practice: ['보상 중복 방지하기','관리자 API 제한하기','구매 성공·실패 흐름 구현하기'],
      artifact: ['GameHub 핵심 서비스','회원·이벤트·보상·포인트·아이템 구매가 연결된 백엔드'],
      criteria: ['로그인 사용자만 보상을 받는다.','관리 기능은 관리자만 실행한다.','동일 보상을 두 번 받지 않는다.','구매 성공 시 포인트와 인벤토리가 함께 변경된다.'],
      questions: [['인증과 인가의 차이는 무엇인가요?',['인증은 누구인지 확인, 인가는 무엇을 할 수 있는지 확인','인증은 데이터 암호화, 인가는 데이터 압축','인가를 통과하면 인증은 필요 없다'],0],['잔액 숫자 하나 대신 포인트 원장(변경 이력)을 두는 이유는 무엇인가요?',['잔액이 왜 이 값이 됐는지 내역으로 추적할 수 있어서','숫자 하나만 저장하면 저장 공간이 부족해서','조회 속도가 항상 빨라져서'],0],['중복 보상을 막는 올바른 방법은 무엇인가요?',['프론트에서 버튼을 비활성화하면 충분하다','지급 전 수령 여부 확인과 지급 기록을 한 작업으로 묶는다','보상 금액을 줄여서 피해를 줄인다'],1]],
      next: ['트랜잭션','롤백','JUnit','동시 요청'] },

    { no: 8, title: '데이터 정합성과 테스트',
      goal: '실패와 중복 요청에도 안전하게 동작하도록 만듭니다.',
      why: '구매·보상 기능은 일부 작업만 성공하면 실제 사용자 피해로 이어질 수 있으므로 트랜잭션과 자동 테스트가 필요합니다.',
      evidence: { type: '우대', quote: '유닛 테스트 및 UI 테스트 작성 경험이 있는 분 · TDD(Test-Driven Development) 개발 방법론 경험' },
      lessons: [['트랜잭션','여러 변경을 하나의 작업처럼 처리합니다.'],['롤백','실패했을 때 이전 상태로 되돌립니다.'],['단위·통합 테스트','로직과 시스템 연결을 각각 검증합니다.'],['동시 요청','같은 요청이 겹쳐도 중복 처리를 막습니다.']],
      practice: ['잔액 부족 테스트','중복 보상 테스트','구매 실패 롤백 확인하기'],
      artifact: ['GameHub 안정성 테스트','핵심 성공·실패·중복 시나리오의 자동 테스트 모음'],
      criteria: ['구매 실패 시 모든 변경이 롤백된다.','중복 보상은 한 번만 성공한다.','핵심 성공·실패 테스트가 존재한다.','테스트 실패 원인을 설명한다.'],
      questions: [['트랜잭션의 목적은 무엇인가요?',['여러 변경을 전부 성공 또는 전부 실패로 묶는다','쿼리 실행 속도를 높인다','테이블 구조를 자동으로 설계한다'],0],['롤백이 필요한 순간은 언제인가요?',['모든 작업이 정상적으로 완료됐을 때','포인트는 차감됐는데 아이템 지급이 실패했을 때','조회만 하고 아무것도 바꾸지 않았을 때'],1],['단위 테스트와 통합 테스트의 차이는 무엇인가요?',['통합 테스트가 있으면 단위 테스트는 필요 없다','단위 테스트는 운영 서버에서만 실행할 수 있다','단위는 로직 하나를 격리해 검증하고, 통합은 DB 등 연결까지 함께 검증한다'],2]],
      next: ['프론트 연동','Docker','배포','포트폴리오 문서'] },

    { no: 9, title: '연동·배포·포트폴리오',
      goal: '완성한 서비스를 실행 가능한 결과물과 지원 자료로 정리합니다.',
      why: '서류에서는 기술 목록보다 실제로 확인할 수 있는 결과물·문제 해결 기록·본인의 역할이 중요하므로 프로젝트를 지원 자료로 변환해야 합니다.',
      evidence: { type: '제출요건', quote: '본인의 개발경험이나 코딩수준을 어필할 수 있는 포트폴리오 첨부 필수 (GitHub, 개인 프로젝트, 팀 프로젝트 등)' },
      lessons: [['프론트 연동','사용자가 API 기능을 실제 화면에서 사용합니다.'],['Docker와 배포','다른 환경에서도 같은 방식으로 실행합니다.'],['프로젝트 문서','ERD·API·실행 방법과 선택 이유를 기록합니다.'],['포트폴리오','공고와 연결된 경험을 사실에 근거해 정리합니다.']],
      practice: ['핵심 화면과 API 연결하기','README만 보고 실행해보기','트러블슈팅 한 건 정리하기'],
      artifact: ['GameHub 포트폴리오','실행 가능한 서비스와 프로젝트·이력서 문서'],
      criteria: ['다른 사람이 실행 방법을 따라 할 수 있다.','핵심 사용자 흐름이 동작한다.','문제와 해결 과정을 기록한다.','AI 활용과 직접 수행한 부분을 구분한다.'],
      questions: [['README에 꼭 들어가야 할 내용은 무엇인가요?',['다른 사람이 따라 할 수 있는 실행 방법과 프로젝트 설명','전체 커밋 목록','데이터베이스 접속 비밀번호'],0],['트러블슈팅 기록의 가치는 무엇인가요?',['문서 분량을 늘려 성실해 보이게 한다','문제를 추적하고 해결한 과정을 보여준다','실패한 시도를 감출 수 있다'],1],['포트폴리오 문장은 무엇을 기준으로 써야 하나요?',['팀 전체가 한 일을 모두 내 경험으로 정리한 것','공고의 요구사항 문장을 그대로 옮긴 것','실제 결과물과 본인이 기여한 범위'],2]],
      next: ['지원서 제출','서류 결과 기록','면접 준비는 별도'] }
  ];

  /* 스테이지별 실행 예제 (학습 모듈 뷰) — 실명 없이 */
  var MODULE_EXAMPLES = [
    { label: 'HelloGame.java', code: 'public class HelloGame {\n    public static void main(String[] args) {\n        String playerName = "player1";\n        int point = 1000;\n\n        System.out.println(playerName + "님의 포인트: " + point);\n    }\n}' },
    { label: 'GamePointCalculator.java', code: 'int point = 1000;\nint itemPrice = 700;\n\nif (point >= itemPrice) {\n    point = point - itemPrice;\n    System.out.println("구매 완료, 남은 포인트: " + point);\n} else {\n    System.out.println("포인트가 부족합니다.");\n}' },
    { label: 'Wallet.java', code: 'public class Wallet {\n    private int balance;\n\n    public void charge(int amount) {\n        if (amount <= 0) throw new IllegalArgumentException();\n        balance += amount;\n    }\n\n    public boolean spend(int amount) {\n        if (amount <= 0 || balance < amount) return false;\n        balance -= amount;\n        return true;\n    }\n}' },
    { label: 'event.html', code: '<button id="rewardButton">보상 받기</button>\n<p id="message"></p>\n\nconst button = document.querySelector("#rewardButton");\nbutton.addEventListener("click", () => {\n    document.querySelector("#message").textContent = "보상을 요청했습니다.";\n});' },
    { label: 'purchase-summary.sql', code: "SELECT\n    u.id,\n    u.name,\n    SUM(p.amount) AS total_amount\nFROM users u\nJOIN purchases p ON p.user_id = u.id\nWHERE p.status = 'COMPLETED'\nGROUP BY u.id, u.name;" },
    { label: '협업 작업 흐름', code: 'git switch -c feature/reward-api\ngit add .\ngit commit -m "feat: 이벤트 보상 API 추가"\ngit switch main\ngit pull\ngit merge feature/reward-api' },
    { label: 'EventController.java', code: '@RestController\n@RequestMapping("/api/events")\npublic class EventController {\n    private final EventService eventService;\n\n    @GetMapping("/{id}")\n    public EventResponse get(@PathVariable Long id) {\n        return eventService.find(id);   // 없으면 404 응답\n    }\n}' },
    { label: 'RewardService.java', code: '@Transactional\npublic void claim(Long userId, Long eventId) {\n    if (rewardRepository.existsByUserIdAndEventId(userId, eventId)) {\n        throw new DuplicateRewardException();   // 사용자당 1회\n    }\n    wallet.charge(event.rewardPoint());\n    rewardRepository.save(new Reward(userId, eventId));\n}' },
    { label: 'PurchaseServiceTest.java', code: '@Test\nvoid 잔액이_부족하면_구매가_실패하고_변경이_없다() {\n    // given: 포인트 100, 가격 700\n    // when: 구매 시도\n    // then: 실패 + 포인트 그대로 + 인벤토리 그대로\n}' },
    { label: 'Dockerfile', code: 'FROM eclipse-temurin:17-jre\nCOPY build/libs/gamehub.jar app.jar\nENTRYPOINT ["java", "-jar", "/app.jar"]' }
  ];

  /* 레슨 상세 개념 override — "단계-레슨" 키. 없으면 템플릿 생성 */
  var LESSON_DETAIL = {
    '1-1': { concept: '조건문은 현재 상태를 검사해 실행할 코드를 선택합니다. 게임 상점에서는 보유 포인트가 가격 이상인지 확인한 뒤 구매 성공과 실패를 나누는 데 사용합니다.',
             points: ['조건식의 결과는 참 또는 거짓입니다.','경계값이 같은 경우를 반드시 확인합니다.','실패 조건을 먼저 처리하면 코드가 단순해질 수 있습니다.'] },
    '1-2': { concept: '반복문은 같은 규칙을 여러 데이터에 적용합니다. 아이템 목록처럼 개수가 달라질 수 있는 데이터를 처리할 때 코드 복사를 줄이고 동일한 규칙을 유지합니다.',
             points: ['반복 대상과 종료 조건을 확인합니다.','각 반복에서 현재 값을 구분합니다.','빈 목록일 때의 결과도 확인합니다.'] },
    '1-3': { concept: '메서드는 입력을 받아 하나의 역할을 수행하고 필요하면 결과를 돌려주는 코드 단위입니다. 구매 가능 검사와 잔액 계산을 분리하면 각각 독립적으로 확인하고 재사용할 수 있습니다.',
             points: ['메서드 하나에는 한 가지 역할을 둡니다.','매개변수는 외부에서 받는 입력입니다.','return은 계산 결과나 처리 상태를 돌려줍니다.'] },
    '2-1': { concept: '캡슐화는 객체의 상태를 외부에서 직접 바꾸지 못하게 막고, 정해진 메서드를 통해서만 변경하게 하는 원칙입니다. 포인트처럼 규칙이 있는 값은 검증을 강제할 수 있습니다.',
             points: ['필드는 private으로 숨깁니다.','상태 변경은 규칙을 검사하는 메서드로만 합니다.','잘못된 입력은 예외나 실패로 처리합니다.'] }
  };

  /* 서술형 시험 문항(공통 1문항) — 객관식만으로는 이해 확인이 부족하므로 추가 */
  var ESSAY_QUESTION = '이번 단계 결과물에서 본인이 직접 작성하거나 수정한 부분과, 그렇게 구현한 이유를 짧게 설명해 주세요.';

  /* ── 시작점 진단 — 이력서 주장마다 검증 문항을 붙인다(형식 혼합, "모르겠어요" 1급 응답).
        문항·결과는 실제 진단 대화 기록을 큐레이팅한 것. 채점은 mock. */
  var ASSESSMENT = [
    { id: 'a1', area: 'Java 컬렉션', format: '코드 완성',
      source: '이력서에 Java·SSAFY 학습을 적으셨어요 — 코드로 확인해볼게요.',
      text: '아이템 목록에서 이름별 개수를 세는 메서드를 완성해 주세요. 반복문·Stream 모두 좋아요.',
      code: 'public static Map<String, Integer> countItems(List<String> items) {\n    // 구현\n}\n\n// 입력: ["검","포션","검","방패","포션","검"]\n// 기대 결과: 검=3, 포션=2, 방패=1' },
    { id: 'a2', area: '객체지향·캡슐화', format: '설명형',
      source: "프로젝트 스택에 'Spring Boot'가 있어요 — 객체 설계부터 확인해볼게요.",
      text: 'Wallet이 setBalance(int)를 public으로 열어두면 어떤 문제가 있나요? 대신 어떤 메서드를 제공하면 좋을까요?',
      code: 'public class Wallet {\n    private int balance;\n    public void setBalance(int balance) { this.balance = balance; }\n}' },
    { id: 'a3', area: 'HTTP 상태 코드', format: '상황형',
      source: "이력서에 'REST API'를 적으셨어요.",
      text: '각 상황에 적절한 HTTP 상태 코드를 적어주세요.\n① 로그인하지 않고 보상 요청\n② 로그인했지만 관리자 기능 접근\n③ 존재하지 않는 이벤트의 보상 요청\n④ 이미 받은 보상 재요청\n⑤ 정상 수령', code: null },
    { id: 'a4', area: 'SQL', format: '직접 작성',
      source: "이력서에 'SQL·JOIN·GROUP BY/HAVING'을 적으셨어요 — 확인해볼게요.",
      text: "완료된 구매(status='COMPLETED')의 총금액이 10,000 이상인 사용자를 (id·이름·총금액)으로, 총금액 내림차순으로 조회하는 SQL을 작성해 주세요.",
      code: 'users(id, name)\npurchases(id, user_id, amount, status, created_at)' },
    { id: 'a5', area: 'Spring 계층', format: '설명형',
      source: "냠냠코치 프로젝트에서 'Spring/Spring Boot'를 사용하셨어요.",
      text: 'POST /api/events/10/rewards/claim 요청이 오면 Controller·Service·Repository가 각각 무슨 일을 하나요? @Transactional은 어디에 붙일까요?', code: null },
    { id: 'a6', area: 'Git', format: '상황형',
      source: "이력서에 'Git 기반 협업'을 적으셨어요.",
      text: 'feature 브랜치 작업 중 다른 팀원이 main의 같은 파일을 수정했어요. 내 작업을 잃지 않고 최신 main을 반영하는 순서를 설명해 주세요.', code: null }
  ];

  var ASSESS_RESULT = {
    verdict: 'Java/Spring을 배운 경험은 있지만, 지금 혼자 구현할 수 있는 상태로 활성화되어 있지는 않아요.',
    verdictNote: '"못한다"는 판정이 아니에요 — 배운 내용이 독립 구현으로 아직 굳지 않은 상태예요. 작은 기능을 직접 만들고 설명하는 반복이 필요해요.',
    confidence: '중간',
    confidenceNote: '컨디션에 따라 실제보다 낮게 나왔을 수 있어요. 결과가 다르다고 느끼면 언제든 다시 진단할 수 있어요.',
    areas: [
      { area: 'Git·작업 흐름', verdict: 'PASS', note: '커밋→pull→충돌 해결→테스트 흐름 이해 확인 — 명령어는 실습으로' },
      { area: 'Java 문법·컬렉션', verdict: 'PARTIAL', note: '반복문 방향은 정확 — Map 활용과 코드 완성 연습 필요' },
      { area: '객체지향·캡슐화', verdict: 'PARTIAL', note: '임의 변경 위험은 이해 — 행위 중심 메서드 설계 연습 필요' },
      { area: 'HTTP 상태 코드', verdict: 'PARTIAL', note: '403·404는 기억 — 401·409 등 전체 지도가 흐림' },
      { area: 'SQL (JOIN·집계)', verdict: 'NEED', note: '기본 SELECT만 — JOIN·GROUP BY 재학습 필요' },
      { area: 'Spring 계층·JPA·트랜잭션', verdict: 'NEED', note: '사용 경험은 있으나 설명이 어려움 — 독립 구현 단계부터' }
    ],
    plan: {
      skip: [{ no: 0, reason: '진단에서 Git 흐름·실행 환경 이해가 확인됐어요' }],
      start: { no: 1, reason: '개념 방향은 알지만 완성된 코드로 표현이 어려워요 — 재활성화부터 시작해요' }
    }
  };

  var AI_RULES = [
    '먼저 혼자 20분 시도하기',
    '막힌 부분을 구체적으로 질문하기',
    '전체 코드 대신 힌트만 요청하기',
    '받은 코드를 한 줄씩 설명해보기',
    '코드를 닫고 다시 작성해보기',
    '작은 요구사항을 추가해 직접 수정하기'
  ];

  var PORTFOLIO_INIT = [
    { key: 'artifact', label: '대표 프로젝트 결과물', status: 'IN_PROGRESS', note: null },
    { key: 'features', label: '단계별 기능 구현', status: 'IN_PROGRESS', note: '1/10' },
    { key: 'docs', label: '프로젝트 문서', status: 'IN_PROGRESS', note: null },
    { key: 'trouble', label: '트러블슈팅 기록', status: 'NOT_STARTED', note: null },
    { key: 'summary', label: '포트폴리오 프로젝트 설명', status: 'NOT_STARTED', note: null },
    { key: 'resume', label: '이력서 프로젝트 항목', status: 'NOT_STARTED', note: null }
  ];

  var FINAL_ITEMS = ['대표 프로젝트 완성','단계별 결과물 검수 완료','단계별 확인 시험 완료','프로젝트 문서 완성','트러블슈팅 기록 완성','포트폴리오 설명 완성','이력서 프로젝트 항목 완성'];

  function reviewsNotRun(){ return [
    { source:'AUTOMATED', label:'자동 테스트', result:'PENDING', text:'미진행' },
    { source:'AI', label:'AI 요구사항 검토', result:'PENDING', text:'미진행' },
    { source:'ADMIN', label:'관리자 검토', result:'PENDING', text:'미진행' } ]; }
  function reviewsRunning(){ return [
    { source:'AUTOMATED', label:'자동 테스트', result:'RUNNING', text:'진행 중' },
    { source:'AI', label:'AI 요구사항 검토', result:'RUNNING', text:'대기 중' },
    { source:'ADMIN', label:'관리자 검토', result:'PENDING', text:'미진행' } ]; }
  function reviewsPassed(){ return [
    { source:'AUTOMATED', label:'자동 테스트', result:'PASS', text:'통과' },
    { source:'AI', label:'AI 요구사항 검토', result:'PASS', text:'통과' },
    { source:'ADMIN', label:'관리자 검토', result:'PENDING', text:'미진행' } ]; }
  function reviewsRevision(){ return [
    { source:'AUTOMATED', label:'자동 테스트', result:'FAIL', text:'조건 2개 미충족' },
    { source:'AI', label:'AI 요구사항 검토', result:'PASS', text:'통과' },
    { source:'ADMIN', label:'관리자 검토', result:'PENDING', text:'미진행' } ]; }

  var MOCK_SUBMISSION = {
    url: 'https://github.com/mock-user/game-wallet',
    desc: 'GameWallet 콘솔 프로그램 1차 제출',
    aiPart: '클래스 구조 초안과 README 목차를 AI로 정리',
    myPart: 'charge/spend 검증 로직과 Map 수량 관리는 직접 작성'
  };

  /* ---------- 상태 구성 ----------
     진단 반영: 0단계는 진단으로 건너뜀(SKIPPED) → 현재 단계는 1단계부터.
     시나리오는 "현재 단계 = 2단계(GameWallet)" 기준으로 학습→결과물→시험 흐름을 보여준다. */
  function baseState(){
    return {
      scenario: 'A',
      goal: GOAL,
      /* 기본 = "빠른 시작" 세계: 이력서 기재(사용자 입력)만 근거로 0·1단계를 건너뛴 상태.
         진단을 거치면 applyAssessment()가 0만 건너뛰고 1단계부터 다시 배치한다 — 그 대비가 데모 포인트. */
      assess: { mode: 'QUICK', result: null },   // PENDING(시작 방식 선택 전) | QUICK | ASSESSED
      skipReasons: {
        0: '이력서에 Git 협업이 기재돼 있어요 (사용자 입력 기준 · 진단 미확인)',
        1: '이력서에 Java·SSAFY 학습이 기재돼 있어요 (사용자 입력 기준 · 진단 미확인)'
      },
      stages: STAGES.map(function (s) {
        var status = 'LOCKED';
        if (s.no === 0) status = 'SKIPPED';
        else if (s.no === 1) status = 'SKIPPED';
        else if (s.no === 2) status = 'IN_PROGRESS';
        return { no: s.no, title: s.title, status: status };
      }),
      currentStage: 2,
      /* 학습(모듈) 게이트: lessonsDone(Set of index) → 4개 모두 완료 시 결과물 열림 */
      learning: { done: [], externalDone: false },
      artifact: { status: 'LOCKED', checks: [null,null,null,null], submission: null, reviews: reviewsNotRun(), feedback: null },
      test: { status: 'LOCKED', answers: {}, wrong: [], attempts: 0 },
      portfolio: JSON.parse(JSON.stringify(PORTFOLIO_INIT)),
      showStageComplete: false,
      showFinal: false,
      finalItems: FINAL_ITEMS
    };
  }

  function cur(s){ return STAGES[s.currentStage]; }
  function learningDone(s){ return s.learning.externalDone || s.learning.done.length >= cur(s).lessons.length; }
  function passArtifact(s){
    s.artifact.status = 'PASSED';
    s.artifact.checks = cur(s).criteria.map(function(){ return true; });
    s.artifact.reviews = reviewsPassed();
    s.artifact.feedback = null;
    if (s.test.status === 'LOCKED') s.test.status = 'READY';
  }
  function allLessons(s){ s.learning.done = cur(s).lessons.map(function(_, i){ return i; }); }

  var SCENARIOS = {
    P: { label: '진단 전 · 시작 방식 선택', build: function (s) {
      s.assess = { mode: 'PENDING', result: null };
      s.skipReasons = {};
      s.stages.forEach(function (st) { st.status = 'LOCKED'; });
      s.currentStage = 1;
      s.artifact.status = 'LOCKED'; s.test.status = 'LOCKED';
    } },
    A: { label: '학습 진행 중 · 결과물·시험 잠금', build: function (s) { s.learning.done = [0]; } },
    B: { label: '학습 완료 · 결과물 검토 중', build: function (s) {
      allLessons(s); s.artifact.status = 'REVIEWING'; s.artifact.submission = MOCK_SUBMISSION; s.artifact.reviews = reviewsRunning();
    } },
    C: { label: '결과물 수정 필요', build: function (s) {
      allLessons(s); s.artifact.status = 'REVISION_REQUIRED'; s.artifact.submission = MOCK_SUBMISSION;
      s.artifact.checks = [true, true, true, false];
      s.artifact.reviews = reviewsRevision();
      s.artifact.feedback = '음수 금액과 잔액 부족 처리 조건이 확인되지 않았어요. 해당 검사를 추가해 다시 제출해 주세요.';
    } },
    D: { label: '결과물 통과 · 시험 시작 가능', build: function (s) { allLessons(s); s.artifact.submission = MOCK_SUBMISSION; passArtifact(s); } },
    E: { label: '시험 진행 중', build: function (s) { allLessons(s); s.artifact.submission = MOCK_SUBMISSION; passArtifact(s); s.test.status = 'IN_PROGRESS'; s.test.attempts = 1; } },
    F: { label: '시험 미통과 · 다시 풀기', build: function (s) {
      allLessons(s); s.artifact.submission = MOCK_SUBMISSION; passArtifact(s);
      s.test.status = 'FAILED'; s.test.attempts = 1; s.test.wrong = [1];
    } },
    G: { label: '단계 완료 · 다음 단계 해금', build: function (s) {
      allLessons(s); s.artifact.submission = MOCK_SUBMISSION; passArtifact(s);
      s.test.status = 'PASSED'; s.test.attempts = 1;
      s.stages[2].status = 'COMPLETED'; s.stages[3].status = 'READY';
      s.portfolio[1].note = '2/10';
      s.showStageComplete = true;
    } },
    H: { label: '전체 완료 · 지원 준비 완료', build: function (s) {
      allLessons(s); s.artifact.submission = MOCK_SUBMISSION; passArtifact(s); s.test.status = 'PASSED';
      s.stages.forEach(function (st) { st.status = st.no === 0 ? 'SKIPPED' : 'COMPLETED'; });
      s.currentStage = 9;
      s.portfolio.forEach(function (p) { p.status = 'COMPLETED'; if (p.key === 'features') p.note = '10/10'; });
      s.showFinal = true; s.showStageComplete = false;
    } }
  };

  /* ── 생성된 커리큘럼(staged-sample.json) 주입 — 목업 STAGES/GOAL을 실데이터로 교체(Phase 3) ──
     생성 데이터 shape: {no,title,goal,why,evidence,detail:{lessons:[{title,desc}],practice[],artifact:{name,desc},criteria[],questions:[{q,options,answer}]}}
     → 목업 shape(lessons:[[t,d]]·artifact:[name,desc]·questions:[[q,[opts],idx]])로 어댑트. 상태머신·MODULE_EXAMPLES·ASSESSMENT는 그대로 둔다. */
  function adaptStage(s){
    var st = {
      no: s.no,
      title: s.title || ('단계 ' + s.no),
      goal: s.goal || '',
      why: s.why || '',
      evidence: s.evidence || { type: '필수', quote: '' },
      lessons: [], practice: [], artifact: ['결과물', ''], criteria: [], questions: [], lessonDetails: [],
      loaded: false,   // 상세 로드 여부 — 개요(lazy)면 false, 정적/주입되면 true
      next: []
    };
    if (s.detail) applyDetailTo(st, s.detail);   // 정적(staged-sample)엔 detail이 이미 있음
    return st;
  }
  // 단계 상세(생성 데이터: lessons[{title,desc}]·questions[{q,options,answer}]·lessonDetails 등)를 목업 stage 모양으로 채운다. 정적/lazy 공용.
  function applyDetailTo(st, d){
    st.lessons = (d.lessons || []).map(function(l){ return [l.title, l.desc]; });
    st.practice = d.practice || [];
    st.artifact = d.artifact ? [d.artifact.name, d.artifact.desc] : ['결과물', ''];
    st.criteria = d.criteria || [];
    st.questions = (d.questions || []).map(function(q){ return [q.q, q.options, q.answer]; });
    st.lessonDetails = d.lessonDetails || [];   // 레슨별 상세(concept·points·example[kind]·guided·challenge·question)
    st.loaded = true;
  }
  function useGenerated(data){
    if (!data || !data.goal || !Array.isArray(data.stages) || !data.stages.length) return false;
    GOAL = {
      posting: data.goal.posting || GOAL.posting,
      track: data.goal.track || GOAL.track,
      project: data.goal.project || GOAL.project,
      projectDesc: data.goal.projectDesc || GOAL.projectDesc,
      userState: data.goal.userState || GOAL.userState
    };
    STAGES = data.stages.map(adaptStage);
    // next(다음에 배울 것 미리보기)는 생성 데이터에 없으므로 다음 단계의 레슨 제목으로 채운다.
    STAGES.forEach(function(st, i){
      var nx = STAGES[i + 1];
      st.next = nx ? nx.lessons.map(function(l){ return l[0]; }).slice(0, 4) : ['지원서 제출', '서류 결과 기록'];
    });
    return true;
  }

  /* ---------- mock service ---------- */
  var state = null, subs = [], reviewTimer = null;
  function emit(){ subs.forEach(function (f) { f(state); }); }

  var RSMock = {
    scenarios: Object.keys(SCENARIOS).map(function (k) { return { key: k, label: SCENARIOS[k].label }; }),
    useGenerated: useGenerated,   // 생성된 커리큘럼 주입(Phase 3) — load 전에 호출
    isStageLoaded: function (no) { return !!(STAGES[no] && STAGES[no].loaded); },
    applyStageDetail: function (no, detail) { if (STAGES[no] && detail) applyDetailTo(STAGES[no], detail); },
    // 라이브(개요만 받은) 시작 상태 — 모든 단계 READY(클릭 가능), 0단계 현재. 단계 클릭 시 상세를 lazy 로드.
    startLive: function () {
      state = baseState();
      state.assess = { mode: 'QUICK', result: null };
      state.skipReasons = {};
      state.stages.forEach(function (st) { st.status = 'READY'; });
      state.currentStage = 0;
      if (state.stages[0]) state.stages[0].status = 'IN_PROGRESS';
      state.learning = { done: [], externalDone: false };
      state.showStageComplete = false; state.showFinal = false;
      emit();
    },
    stageData: function (no) { return STAGES[no]; },
    moduleExample: function (no) { return MODULE_EXAMPLES[no]; },
    essayQuestion: ESSAY_QUESTION,

    /** 레슨 상세 — 생성된 lessonDetails가 있으면 그걸(진짜), 없으면 override/템플릿(폴백). */
    lessonDetail: function (stageNo, lessonIdx) {
      var st = STAGES[stageNo];
      var pair = st.lessons[lessonIdx];
      var gen = st.lessonDetails && st.lessonDetails[lessonIdx];
      if (gen) {
        return {
          title: pair[0],
          goal: pair[1],
          concept: gen.concept || '',
          points: gen.points || [],
          example: gen.example || null,   // {kind, label, content}
          guided: (gen.guided && gen.guided.length) ? gen.guided : st.practice,
          challenge: gen.challenge || (st.criteria[lessonIdx] || st.criteria[0] || ''),
          question: gen.question ? [gen.question.q, gen.question.options, gen.question.answer]
                                 : st.questions[lessonIdx % st.questions.length]
        };
      }
      var ov = LESSON_DETAIL[stageNo + '-' + lessonIdx];
      return {
        title: pair[0],
        goal: pair[1] + ' 설명을 읽고 실행 예제를 바꿔본 뒤, 작은 변형 과제를 혼자 완성하는 것이 이번 레슨의 목표입니다.',
        concept: ov ? ov.concept : pair[1] + ' 이 개념을 외우는 것보다 어떤 문제를 해결하는지 이해하고, 현재 단계의 결과물에서 직접 사용해보는 것이 중요합니다.',
        points: ov ? ov.points : [
          pair[0] + '이(가) 해결하는 문제를 자신의 말로 설명합니다.',
          '예제를 실행한 뒤 값 하나를 바꿔 결과를 비교합니다.',
          '최종 결과물에서 ' + pair[0] + '이(가) 사용된 위치를 기록합니다.'
        ],
        example: MODULE_EXAMPLES[stageNo],
        guided: st.practice,
        challenge: (st.criteria[lessonIdx] || st.criteria[0]) + ' — 안내 문구를 보지 않고 직접 수행하고, 변경 전후를 커밋으로 남겨보세요.',
        question: st.questions[lessonIdx % st.questions.length]
      };
    },

    load: function (key) {
      if (reviewTimer) { clearTimeout(reviewTimer); reviewTimer = null; }
      state = baseState();
      state.scenario = key || 'A';
      (SCENARIOS[state.scenario] || SCENARIOS.A).build(state);
      emit();
    },
    getState: function () { return state; },
    isLearningDone: function () { return learningDone(state); },
    subscribe: function (f) { subs.push(f); },

    /** 레슨 이해 확인 통과 → 완료 처리. 전부 완료되면 결과물 잠금 해제 */
    completeLesson: function (idx) {
      if (state.learning.done.indexOf(idx) < 0) state.learning.done.push(idx);
      if (learningDone(state) && state.artifact.status === 'LOCKED') state.artifact.status = 'NOT_SUBMITTED';
      emit();
    },
    /** 외부에서 이미 학습함 — 학습 게이트 통과 처리 */
    markExternalDone: function () {
      state.learning.externalDone = true;
      if (state.artifact.status === 'LOCKED') state.artifact.status = 'NOT_SUBMITTED';
      emit();
    },

    /* ── 시작점 진단 ── */
    assessment: function () { return { questions: ASSESSMENT, result: ASSESS_RESULT }; },
    aiRules: function () { return AI_RULES; },

    /** 빠른 시작 — 이력서(사용자 입력) 기준으로 즉시 시작. → 추후 POST .../start {mode:'quick'} */
    chooseQuick: function () {
      var sc = state.scenario;
      state = baseState(); state.scenario = sc;
      SCENARIOS.A.build(state); state.learning.done = [];
      emit();
    },

    /** 진단 제출 — 채점은 mock(큐레이팅 결과 적용). 0단계만 건너뛰고 1단계부터 배치.
        → 추후 POST .../assessment {answers} → {result, plan} */
    applyAssessment: function (answers) {
      state.assess = { mode: 'ASSESSED', result: ASSESS_RESULT, answers: answers || {} };
      state.skipReasons = { 0: ASSESS_RESULT.plan.skip[0].reason };
      state.stages.forEach(function (st) {
        st.status = st.no === 0 ? 'SKIPPED' : (st.no === 1 ? 'IN_PROGRESS' : 'LOCKED');
      });
      state.currentStage = 1;
      state.learning = { done: [], externalDone: false };
      state.artifact = { status: 'LOCKED', checks: STAGES[1].criteria.map(function(){ return null; }),
                        submission: null, reviews: reviewsNotRun(), feedback: null };
      state.test = { status: 'LOCKED', answers: {}, wrong: [], attempts: 0 };
      emit();
    },

    submitArtifact: function (form) {
      state.artifact.status = 'REVIEWING';
      state.artifact.submission = form;
      state.artifact.reviews = reviewsRunning();
      state.artifact.feedback = null;
      emit();
      reviewTimer = setTimeout(function () { passArtifact(state); emit(); }, 1600);
    },

    startTest: function () { state.test.status = 'IN_PROGRESS'; state.test.attempts += 1; state.test.answers = {}; emit(); },
    submitTest: function (answers) {
      state.test.answers = answers || {};
      state.test.status = 'PASSED'; state.test.wrong = [];
      state.stages[state.currentStage].status = 'COMPLETED';
      var nxt = state.stages[state.currentStage + 1];
      if (nxt && nxt.status === 'LOCKED') nxt.status = 'READY';
      state.showStageComplete = true;
      emit();
    },
    retryTest: function () { state.test.status = 'IN_PROGRESS'; state.test.wrong = []; emit(); },

    /** 다음 단계 시작 — 현재 완료 유지, 다음 단계 IN_PROGRESS + 게이트 초기화 */
    nextStage: function () {
      state.currentStage += 1;
      state.stages[state.currentStage].status = 'IN_PROGRESS';
      state.learning = { done: [], externalDone: false };
      state.artifact = { status: 'LOCKED', checks: STAGES[state.currentStage].criteria.map(function(){ return null; }),
                        submission: null, reviews: reviewsNotRun(), feedback: null };
      state.test = { status: 'LOCKED', answers: {}, wrong: [], attempts: 0 };
      state.showStageComplete = false;
      emit();
    },

    /** 아무 단계나 열어 보기(복습·QA) — currentStage 이동 + 그 단계 게이트 초기화. 건너뛴 0단계도 접근 가능. */
    gotoStage: function (no) {
      if (no == null || no < 0 || no >= STAGES.length) return;
      state.currentStage = no;
      state.learning = { done: [], externalDone: false };
      state.artifact = { status: 'LOCKED', checks: STAGES[no].criteria.map(function(){ return null; }),
                        submission: null, reviews: reviewsNotRun(), feedback: null };
      state.test = { status: 'LOCKED', answers: {}, wrong: [], attempts: 0 };
      state.showStageComplete = false;
      emit();
    }
  };

  window.RSMock = RSMock;
})();
