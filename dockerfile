FROM python:slim
LABEL org.opencontainers.image.authors="zklosko@hopecentral.com"

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000/tcp
EXPOSE 4703/udp

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]