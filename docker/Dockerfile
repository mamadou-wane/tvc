FROM ubuntu:26.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ cmake git ca-certificates python3 python3-matplotlib python3-pip make \
    && rm -rf /var/lib/apt/lists/*
# System Python is PEP 668 externally managed; this image is disposable.
RUN pip3 install --break-system-packages google-crc32c
