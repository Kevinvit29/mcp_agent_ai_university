FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Tesseract OCR is needed for scanned Thai/English PDF files.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr \
       tesseract-ocr-eng \
       tesseract-ocr-tha \
       libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repository root. Keep the backend source and utility
# scripts explicit, so no .env or unrelated files are added to the image.
COPY backend/requirements-lock.txt ./
# Install pinned groups in separate cacheable layers. This keeps a temporary
# package-host timeout from discarding every large PDF/data/ML wheel.
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt \
    fastapi uvicorn requests pydantic pymongo psycopg2-binary python-multipart
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt numpy
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt pandas openpyxl xlrd
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt pypdf PyMuPDF Pillow pytesseract reportlab chardet urllib3
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt google-genai
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt scipy
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt joblib threadpoolctl
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt scikit-learn
RUN pip install --no-cache-dir --timeout 600 --retries 8 \
    -c requirements-lock.txt pytest

COPY backend/app ./app
COPY mcp_server/app ./mcp_server/app
COPY scripts ./scripts
COPY tests ./tests

# Keep a source-layout copy for deterministic tests that verify packaged
# configuration and launchers. Runtime imports continue to use /app/app above.
COPY backend ./backend
COPY frontend ./frontend
COPY database ./database
COPY docs ./docs
COPY .github ./.github
COPY docker-compose.yml ./
COPY START_UNIVERSITY_AI.bat START_V30.bat CHECK_V30_SYSTEM.bat ./
COPY RESET_ADMIN_AND_START.bat RECOVER_ADMIN_V30.bat ./
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
