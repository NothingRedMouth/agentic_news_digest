FROM nvidia/cuda:13.2.1-cudnn-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    cmake \
    git \
    ninja-build \
    cron \
    && rm -rf /var/lib/apt/lists/*

ENV GGML_CUDA=1
ENV FORCE_CMAKE=1
ENV CMAKE_ARGS="-DGGML_CUDA=on"

WORKDIR /app
COPY requirements.txt .
COPY main.py .
COPY run.sh .

RUN mkdir -p /app/models

RUN pip install --no-cache-dir -r requirements.txt

RUN chmod +x /app/run.sh

RUN echo "0 3 * * 0 root /app/run.sh >> /var/log/cron.log 2>&1" > /etc/cron.d/digest-cron \
    && chmod 0644 /etc/cron.d/digest-cron \
    && crontab /etc/cron.d/digest-cron

RUN touch /var/log/cron.log

CMD ["sh", "-c", "cron && tail -f /var/log/cron.log"]
