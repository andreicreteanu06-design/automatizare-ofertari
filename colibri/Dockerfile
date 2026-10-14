# Bazat pe docker/Dockerfile.slim din JustVugg/colibri, dar cu motoarele
# qwen36 (Creierul Intern) și laya (verificator), nu doar GLM.
# Pin COLIBRI_REF la un commit testat înainte de producție.
FROM debian:stable-slim AS build
ARG COLIBRI_REF=main
ARG ARCH=x86-64-v3
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential make git ca-certificates && \
    rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${COLIBRI_REF} https://github.com/JustVugg/colibri.git /src
RUN make -C /src/c qwen36 laya ARCH=${ARCH}

FROM debian:stable-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 libgomp1 && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m -u 1000 colibri
# Launcher-ul caută binarele motoarelor lângă el (engine_for -> HERE), deci
# copiem tot c/ (doar Python stdlib + binare). Fără COLI_ENGINE/COLI_DOCKER_GLM_ONLY.
COPY --from=build /src/c /app
WORKDIR /app
ENV PYTHONUNBUFFERED=1
VOLUME ["/model"]
EXPOSE 5000
USER colibri
ENTRYPOINT ["python3", "/app/coli"]
CMD ["doctor", "--model", "/model"]
