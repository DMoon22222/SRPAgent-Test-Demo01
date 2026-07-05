FROM eclipse-temurin:17-jdk-jammy

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates bash \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

CMD ["bash", "-lc", "java -version && python3 --version"]
