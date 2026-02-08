FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu128 \
    CUDA_HOME=/usr/local/cuda \
    TMPDIR=/var/tmp

RUN mkdir -p /var/tmp /tmp && chmod 1777 /var/tmp /tmp

RUN apt-get update -o Dir::Cache::temp=/var/tmp \
    && apt-get install -y --no-install-recommends \
    software-properties-common \
    build-essential \
    git \
    curl \
    ca-certificates \
    ffmpeg \
    sox \
    libsox-dev \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update -o Dir::Cache::temp=/var/tmp \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && python3 -m ensurepip --upgrade

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY InnoFranceApp/docker/requirements.lock.txt /tmp/requirements.lock.txt

RUN python3 -m pip install --upgrade \
      pip==25.3 \
      setuptools==80.10.1 \
      wheel==0.46.3

RUN pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 \
    --index-url https://download.pytorch.org/whl/cu128

    
RUN python3 -m pip install -r /tmp/requirements.lock.txt --no-deps --no-build-isolation

RUN pip install flash-attn==2.8.3 --no-build-isolation
    
RUN git clone https://github.com/MoonshotAI/Kimi-Audio /workspace/Kimi-Audio \
    && python3 -m pip install -e /workspace/Kimi-Audio

COPY InnoFranceApp/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/bin/bash"]
