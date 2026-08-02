FROM eclipse-temurin:17-jdk-alpine AS build
WORKDIR /workspace
COPY gradlew settings.gradle build.gradle ./
COPY gradle ./gradle
RUN chmod +x gradlew
COPY src ./src
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:17-jre-alpine
RUN addgroup -S jobiss && adduser -S jobiss -G jobiss
WORKDIR /app
COPY --from=build /workspace/build/libs/*.jar /app/jobiss-backend.jar
USER jobiss
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/jobiss-backend.jar"]
