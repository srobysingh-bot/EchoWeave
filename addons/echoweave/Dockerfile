ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    curl \
    jq \
    bash \
    ffmpeg

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
