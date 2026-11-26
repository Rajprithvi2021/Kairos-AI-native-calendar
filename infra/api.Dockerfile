FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY services/api/pyproject.toml services/api/uv.lock services/api/README.md ./
RUN uv sync --frozen --no-dev
COPY services/api/app ./app
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
