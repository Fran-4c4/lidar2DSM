FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
LABEL org.opencontainers.image.title="lidar2DSM"
LABEL org.opencontainers.image.description="Local LAS/LAZ to aligned DTM, DSM and nDSM GeoTIFFs"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.authors="Francisco Rafael Moreno Santana"
LABEL org.opencontainers.image.source="https://github.com/Fran-4c4/lidar2DSM"
WORKDIR /app
# Rasterio's Linux wheel loads Expat dynamically; the slim base omits it.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY constraints ./constraints
RUN pip install --no-cache-dir -c constraints/python312.txt .
WORKDIR /data
ENTRYPOINT ["lidar2dsm"]
