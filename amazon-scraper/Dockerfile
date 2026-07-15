FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖（Playwright 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright 浏览器（仅 Chromium）
RUN playwright install-deps chromium && \
    playwright install chromium

# 复制项目文件
COPY . .

# 创建数据和日志目录
RUN mkdir -p data logs

# 暴露 Web 端口
EXPOSE 8000

# 默认启动 Web Dashboard
CMD ["python", "main.py", "web"]
