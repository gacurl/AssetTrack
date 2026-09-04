# Dockerfile
FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d

RUN python -m pip install --upgrade "pip==26.2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Keep base OS packages patched (pulls fixed libpng, etc.)
RUN apk update && apk upgrade --no-cache

RUN addgroup -S -g 101 assettrack \
    && adduser -S -u 100 -G assettrack -h /app assettrack

# System deps for common scientific + imaging stacks
RUN apk add --no-cache --upgrade \
        libpng \
        libjpeg-turbo \
        freetype \
        lcms2 \
        libwebp \
        tiff \
        openjpeg \
        harfbuzz \
        fribidi \
        zlib \
        libstdc++ \
        openblas \
    && apk add --no-cache --virtual .build-deps \
        build-base \
        gfortran \
        musl-dev \
        linux-headers \
        libffi-dev \
        openssl-dev \
        zlib-dev \
        jpeg-dev \
        freetype-dev \
        lcms2-dev \
        libwebp-dev \
        tiff-dev \
        openjpeg-dev \
        harfbuzz-dev \
        fribidi-dev \
        openblas-dev

# Install deps first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall --yes pip \
    && apk del .build-deps

# Copy the app (includes assettrack/ + templates/)
COPY . /app
RUN mkdir -p /app/data \
    && chown -R assettrack:assettrack /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3); sys.exit(0)"

USER assettrack

# Run the intake app exactly like local
CMD ["python", "-m", "assettrack.intake.app"]
