# syntax=docker/dockerfile:1.7
#
#   cpu : NLU · 문구 · 챗봇 UI · API
#   gpu : 이미지 생성 (SDXL · rembg)
#
# 의존성은 pyproject.toml extras 를 그대로 설치한다. 버전은 한 곳에서만 관리.

ARG PYTHON_VERSION=3.12
ARG CUDA_IMAGE=nvidia/cuda:12.6.2-cudnn-runtime-ubuntu24.04


# ─────────────────────────── cpu ───────────────────────────
FROM python:${PYTHON_VERSION}-slim AS cpu

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# fonts-nanum 이 없으면 레이아웃 합성에서 한글이 깨진다
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-nanum fontconfig curl git \
    && fc-cache -f && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 정의만 먼저 복사 — 코드를 고쳐도 재설치하지 않는다
COPY pyproject.toml README.md ./
RUN mkdir -p src/api src/app_core \
    && touch src/api/__init__.py src/app_core/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e ".[dev,ui,llm]"

COPY . .
EXPOSE 8000 8501
CMD ["streamlit", "run", "demo/app_chat.py", "--server.port=8501"]


# ─────────────────────────── gpu ───────────────────────────
FROM ${CUDA_IMAGE} AS gpu

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV DEBIAN_FRONTEND=noninteractive
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# 모델 캐시. compose 가 볼륨으로 마운트한다 (SDXL 하나가 7GB)
ENV HF_HOME=/models
ENV HF_HUB_DISABLE_PROGRESS_BARS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip \
        fonts-nanum fontconfig curl git \
        libgl1 libglib2.0-0 \
    && fc-cache -f && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 는 시스템 파이썬 직접 설치를 막는다(PEP 668)
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app

COPY pyproject.toml README.md ./
RUN mkdir -p src/api src/app_core \
    && touch src/api/__init__.py src/app_core/__init__.py

# CUDA 휠 torch 를 먼저. 순서를 바꾸면 CPU 전용 torch 가 깔린다
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url ${TORCH_INDEX}
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e ".[dev,ui,ml]"

COPY . .
EXPOSE 8000 8501
CMD ["python", "-c", "import torch; print('CUDA:', torch.cuda.is_available())"]
