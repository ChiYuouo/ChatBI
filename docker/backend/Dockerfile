# ChatBI 后端镜像（FastAPI + ChromaDB）
# 构建上下文为项目根目录（见 docker-compose.yml 的 build.context）

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 走阿里云源安装 uv，避免 ghcr.io 拉不动
RUN pip install uv -i https://mirrors.aliyun.com/pypi/simple/

# 先按锁文件装依赖，让这层能被代码改动复用缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再拷贝源码与运行时依赖的数据文件
COPY src/ ./src/
COPY api_service.py main.py ./
RUN uv sync --frozen --no-dev

# 以下是运行时真实依赖，缺失会在启动或检索时报错：
#   indicators.json      指标知识（相对 CWD 读取，必须在 /app 下）
#   indicators_full.json 指标目录（query_decomposer 用 parents[3] 绝对寻址）
#   chroma_db/           Schema Linking 与指标 RAG 的向量索引
#   data/                评测用例等数据
COPY indicators.json indicators_full.json ./
COPY chroma_db/ ./chroma_db/
COPY data/ ./data/

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "api_service:app", "--host", "0.0.0.0", "--port", "8000"]
