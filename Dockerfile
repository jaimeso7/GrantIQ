FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt
COPY . .
RUN useradd --create-home --uid 10001 grantiq && mkdir -p /app/data && chown -R grantiq:grantiq /app
USER grantiq
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "grantiq.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
