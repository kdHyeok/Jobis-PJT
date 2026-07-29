# syntax=docker/dockerfile:1
# JOBIS backend — 빌드/런타임 2단계 이미지
# CI가 이미 만든 jar을 재사용할 때는: docker build --build-arg PREBUILT_JAR=backend.jar .

# ── 1단계: 빌드 (Gradle) ──────────────────────────────────
FROM eclipse-temurin:17-jdk AS build
WORKDIR /build

# 의존성 레이어를 소스와 분리해 캐시 (build.gradle이 안 바뀌면 재다운로드 없음)
COPY gradlew build.gradle settings.gradle ./
COPY gradle gradle
RUN chmod +x gradlew && ./gradlew --no-daemon dependencies --quiet || true

COPY src src
RUN ./gradlew --no-daemon bootJar \
 && jar="$(find build/libs -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' -print -quit)" \
 && test -n "$jar" \
 && cp "$jar" /build/app.jar

# ── 2단계: 런타임 (JRE만) ─────────────────────────────────
FROM eclipse-temurin:17-jre
RUN useradd --system --home-dir /app --shell /usr/sbin/nologin jobis
WORKDIR /app
COPY --from=build /build/app.jar app.jar
USER jobis
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
