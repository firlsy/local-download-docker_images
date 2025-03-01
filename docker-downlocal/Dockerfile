# Dockerfile
FROM python:3.10-slim-bullseye

# 安装必要依赖
RUN apt-get update && apt-get install -y \
    curl \
    zip unzip \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# 安装 Docker CLI
RUN curl -fsSL https://get.docker.com | sh

# 创建工作目录
WORKDIR /app
COPY docker-downlocal.py config_docker-downlocal.conf ./

# 设置默认存储路径
ENV REMOTE_PATH=/data/docker-images

# 设置入口点
ENTRYPOINT ["python", "docker-downlocal.py"]
