FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils build-essential gdal-bin gettext libgdal-dev libproj-dev \
    netcat-openbsd postgresql-client \
    && rm -rf /var/lib/apt/lists/*
COPY REQUIREMENTS.txt /app/REQUIREMENTS.txt
COPY deployment/requirements.txt deployment/constraints.txt /app/deployment/
RUN pip install --no-cache-dir -r deployment/requirements.txt
COPY . /app
RUN groupadd --gid 10001 miyp && useradd --uid 10001 --gid miyp --no-create-home miyp \
    && mkdir -p /app/static /app/main_app/media \
    && chown -R miyp:miyp /app/static /app/main_app/media
USER 10001:10001
EXPOSE 8000
CMD ["daphne", "--bind", "0.0.0.0", "--port", "8000", "--http-timeout", "60", "--application-close-timeout", "30", "--access-log", "/dev/null", "--no-server-name", "deployment.asgi:application"]
