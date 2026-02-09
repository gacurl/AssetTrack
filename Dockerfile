# Dockerfile
FROM python:3.12-alpine

RUN python -m pip install --upgrade "pip==26.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for common scientific + imaging stacks
RUN apk add --no-cache \
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
    && apk del .build-deps

# Copy the app (includes assettrack/ + templates/)
COPY . /app

EXPOSE 8000

# Run the intake app exactly like local
CMD ["python", "-m", "assettrack.intake.app"]
