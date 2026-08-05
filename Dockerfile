# syntax=docker/dockerfile:1.7
#
# 동네 매장 광고 만들기 — 기본 파이프라인
#
# 스테이지가 둘이다. 기술계획서 8장의 단계별 계획과 대응한다.
#
#   app  (CPU, 기본)  — 지금 동작하는 것: 챗봇 흐름 · 레이아웃 합성 · 룰 엔진 · 레지스트리
#                       생성 부분은 스텁이라 GPU 가 필요 없다. 이미지가 가볍고 빌드가 빠르다.
#   gpu  (CUDA)       — 모델을 붙인 뒤(단계 3~6). torch · diffusers · ControlNet 등.
#
# 지금 팀에 공유하고 데모하는 용도는 app 스테이지로 충분하다.
# 모델 선정이 끝나면 requirements-gpu.txt 를 채우고 gpu 스테이지로 넘어간다.
#
# ── 사용법 ──────────────────────────────────────────────────────
#   # CPU — 챗봇 흐름 데모
#   docker build -t ad-maker .
#   docker run --rm -p 8501:8501 ad-maker
#
#   # 폼 방식 프로토타입을 보고 싶으면
#   docker run --rm -p 8501:8501 ad-maker streamlit run app.py
#
#   # GPU — 모델 붙인 뒤. 모델 캐시는 반드시 볼륨으로 (SDXL 하나가 7GB 안팎)
#   docker build --target gpu -t ad-maker:gpu .
#   docker run --rm --gpus all -p 8501:8501 -v ad-models:/models ad-maker:gpu
# ───────────────────────────────────────────────────────────────

# ⚠️ FROM 에서 쓰는 ARG 는 반드시 첫 FROM 이전(전역 스코프)에 선언해야 한다.
#    스테이지 안에서 선언하면 그 스테이지에만 적용돼 FROM 이 빈 값을 받는다.
ARG PYTHON_VERSION=3.12
ARG CUDA_IMAGE=nvidia/cuda:12.6.2-cudnn-runtime-ubuntu24.04


# ══════════════════════════════════════════════════════════════
# app — CPU 기본 이미지
# ══════════════════════════════════════════════════════════════
FROM python:${PYTHON_VERSION}-slim AS app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# 컨테이너에서 Streamlit 을 띄우려면 headless + 0.0.0.0 바인딩이 필요하다
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# ⚠️ fonts-nanum 이 없으면 레이아웃 합성에서 한글이 전부 깨진다.
#    리눅스에는 한글 폰트가 기본 탑재되지 않는다 — 기술계획서 9장 리스크.
#    src/layout.py 가 /usr/share/fonts/truetype/nanum/ 을 탐색한다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-nanum \
        curl \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성을 먼저 복사해 레이어 캐시를 살린다 — 코드만 고칠 때 재설치하지 않는다
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

# 비root 실행
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# 기본은 챗봇 흐름 데모. 폼 방식을 보려면 실행 시 app.py 로 덮어쓴다.
CMD ["streamlit", "run", "app_chat.py"]


# ══════════════════════════════════════════════════════════════
# gpu — 모델을 붙인 뒤 사용 (단계 3~6)
# ══════════════════════════════════════════════════════════════
#
# ⚠️ CUDA_IMAGE 는 **배포 대상 GPU 드라이버에 맞춰 반드시 확인**할 것.
#    GCP VM 의 GPU 스펙이 아직 미확인이다 (기술계획서 5-3).
#    - 태그 존재 여부: https://hub.docker.com/r/nvidia/cuda/tags
#    - ubuntu24.04 계열을 쓰는 이유는 python3.12 가 기본이기 때문
#      (pyproject 의 requires-python >=3.12 와 일치)
#    - 22.04 를 써야 한다면 python3.12 를 따로 설치해야 한다
#
#    빌드 시 교체:  docker build --target gpu \
#                     --build-arg CUDA_IMAGE=nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 .
#
#    (기본값은 파일 최상단 전역 ARG 에 있다)
FROM ${CUDA_IMAGE} AS gpu

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV DEBIAN_FRONTEND=noninteractive

ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# 모델 가중치 캐시. 반드시 볼륨으로 마운트할 것 — 안 하면 재빌드마다 수십 GB 를 다시 받는다
ENV HF_HOME=/models
ENV HF_HUB_DISABLE_PROGRESS_BARS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip \
        fonts-nanum \
        curl \
        # rembg(onnxruntime)·opencv 계열이 요구하는 런타임 라이브러리
        libgl1 \
        libglib2.0-0 \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 는 시스템 파이썬에 직접 설치하는 것을 막는다(PEP 668). venv 를 쓴다.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app

COPY requirements.txt requirements-gpu.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt -r requirements-gpu.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /models \
    && chown -R appuser:appuser /app /models
USER appuser

EXPOSE 8501

# 모델 로딩이 오래 걸리므로 start-period 를 길게 잡는다
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app_chat.py"]