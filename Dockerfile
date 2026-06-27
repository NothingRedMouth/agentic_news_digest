FROM nvidia/cuda:13.2.1-cudnn-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    cmake \
    git \
    ninja-build \
    cron \
    curl \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

ENV GGML_CUDA=1
ENV FORCE_CMAKE=1
ENV CMAKE_ARGS="-DGGML_CUDA=on"

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt --break-system-packages

COPY . .

RUN mkdir -p /app/configs /app/chroma_db /app/models /app/logs

EXPOSE 5672 15672

COPY run.sh /run.sh
RUN dos2unix /run.sh && chmod +x /run.sh
ENTRYPOINT ["/run.sh"]
