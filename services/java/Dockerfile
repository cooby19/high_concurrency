# syntax=docker/dockerfile:1
FROM eclipse-temurin:21.0.6_7-jdk-jammy AS build
WORKDIR /app
RUN --mount=type=secret,id=proxy_ca if [ -f /run/secrets/proxy_ca ]; then export CURL_CA_BUNDLE=/run/secrets/proxy_ca; fi; curl --fail -o gson.jar https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.12.1/gson-2.12.1.jar
COPY Main.java .
RUN javac -cp gson.jar Main.java && java -version > /app/build-info.txt 2>&1 && sha256sum gson.jar >> /app/build-info.txt
FROM eclipse-temurin:21.0.6_7-jre-jammy
WORKDIR /app
COPY --from=build /app /app
COPY --from=build /app/build-info.txt /build-info.txt
ENV JAVA_TOOL_OPTIONS="-Djdk.httpclient.disableRetryConnect=true -Djdk.httpclient.enableAllMethodRetry=false -Djdk.httpclient.redirects.retrylimit=1"
CMD ["java", "-cp", ".:gson.jar", "Main"]
