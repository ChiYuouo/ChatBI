# ChatBI 后端镜像（FastAPI + ChromaDB）
# 构建上下文为项目根目录（见 docker-compose.yml 的 build.context）

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 安装 uv；避免镜像源大文件下载卡住构建
RUN pip install uv --index-url https://pypi.org/simple/ --timeout 20 --retries 2

# 先按锁文件装依赖，让这层能被代码改动复用缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再拷贝源码与运行时依赖的数据文件
COPY src/ ./src/
COPY api_service.py ./
RUN uv sync --frozen --no-dev

# 索引由初始化命令创建并持久化，构建不依赖本机索引或模型调用。
COPY indicators_full.json ./
COPY data/ ./data/

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "api_service:app", "--host", "0.0.0.0", "--port", "8000"]
