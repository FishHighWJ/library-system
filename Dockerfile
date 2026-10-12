# 图书馆管理系统 - Dockerfile
# 基于 python:3.11-slim 精简镜像，避免过度工程（不引入 nginx/gunicorn）
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，避免 Python 写 pyc + 实时刷新日志
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_CONFIG=production

# 安装系统依赖（gcc 用于编译 sklearn/numpy）
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖清单，利用 Docker 缓存层加速构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 暴露 Flask 端口
EXPOSE 5000

# 初始化数据库（如未生成）并启动应用
# app.py 默认监听 0.0.0.0:5000
CMD ["sh", "-c", "python init_db.py && python app.py"]
