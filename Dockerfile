# Precisa de Docker (não runtime nativo do Render) porque a leitura do eGAR
# usa OCR (pytesseract), que depende do binário `tesseract-ocr` do sistema —
# esse pacote não está disponível nos runtimes nativos do Render, só via
# apt-get em uma imagem Docker.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend

CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
