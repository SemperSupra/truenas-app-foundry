# Disposable public-source CPU startup probe. NOT a production or published image.
# Build context is the exact checked-out upstream public source commit.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgl1 libglib2.0-0 ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/comfy
COPY requirements.txt .
# Use the CPU wheel index explicitly; the probe fails if dependency resolution substitutes a CUDA build.
RUN python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.9.1 torchvision==0.24.1 \
 && python -m pip install -r requirements.txt \
 && python -m pip check \
 && python -c 'import torch; assert torch.version.cuda is None, torch.__version__; print(torch.__version__)'
COPY . .
RUN useradd --uid 10001 --create-home probe && chown -R 10001:10001 /opt/comfy
USER 10001:10001
CMD ["python","main.py","--cpu","--listen","127.0.0.1","--port","8188","--offline","--disable-all-custom-nodes","--disable-auto-launch","--disable-assets","--disable-dynamic-vram"]
