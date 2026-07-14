FROM python:3.11-slim

# psycopg2 needs libpq at build time
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Installs the `bonaid` command as an entrypoint (see pyproject.toml)
RUN pip install --no-cache-dir -e .

ENTRYPOINT ["bonaid"]
CMD ["status"]
