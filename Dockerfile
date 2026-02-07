# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app (includes assettrack/ + templates/)
COPY . /app

EXPOSE 8000

# Run the intake app exactly like local
CMD ["python", "-m", "assettrack.intake.app"]