ARG BUILD_FROM
FROM ${BUILD_FROM}

ARG BUILD_ARCH

RUN apk add --no-cache \
    curl \
    jq \
    bash \
    ffmpeg

# Install cloudflared for automatic tunneling
RUN ARCH="$(uname -m)"; \
    case "$ARCH" in \
      x86_64)  CF_ARCH="amd64" ;; \
      aarch64) CF_ARCH="arm64" ;; \
      armv7l)  CF_ARCH="arm"   ;; \
      armhf)   CF_ARCH="arm"   ;; \
      *)       CF_ARCH="amd64" ;; \
    esac; \
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
      -o /usr/local/bin/cloudflared && \
    chmod +x /usr/local/bin/cloudflared

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /app
COPY app/ /app/app/

COPY run.sh /run.sh
RUN chmod +x /run.sh

VOLUME ["/data"]

ENTRYPOINT ["/init"]
CMD ["/run.sh"]
