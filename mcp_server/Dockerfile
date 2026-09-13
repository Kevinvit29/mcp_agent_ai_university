FROM python:3.11-slim
WORKDIR /app
# pytesseract calls the Tesseract executable. The Python dependencies use
# binary wheels, so compiler and development packages are unnecessary here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-lock.txt .
RUN pip install --no-cache-dir --timeout 600 --retries 8 -r requirements-lock.txt
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
