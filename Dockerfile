FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        binutils \
        build-essential \
        curl \
        gdal-bin \
        gettext \
        libgdal-dev \
        libproj-dev \
        netcat-openbsd \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY REQUIREMENTS.txt /app/REQUIREMENTS.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r REQUIREMENTS.txt

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY . /app

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
