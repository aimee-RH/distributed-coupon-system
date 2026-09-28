FROM python:3.12-alpine
WORKDIR /app
COPY demo/requirements.txt /app/demo/requirements.txt
RUN pip install --no-cache-dir -r /app/demo/requirements.txt
COPY demo /app/demo
COPY benchmarks/metrics.prom /app/benchmarks/metrics.prom
CMD ["python", "demo/server.py"]
