ARG BUILD_FROM
FROM ${BUILD_FROM}

# ---------- system deps ----------
RUN apk add --no-cache \
    curl \
    jq \
    bash

# ---------- Python deps ----------
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ---------- application code ----------
WORKDIR /app
COPY app/ /app/app/

# ---------- entrypoint ----------
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Persistent data directory (mapped by HA)
VOLUME ["/data"]

ENTRYPOINT ["/run.sh"]
