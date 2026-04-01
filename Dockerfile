FROM python:3.11-slim

WORKDIR /app

# Install dependencies dulu (layer terpisah agar cache efisien)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY bot/ ./bot/
COPY main.py .

# Jangan run sebagai root
RUN useradd -m botuser
USER botuser

# ENV default — akan di-override oleh Secret Manager saat runtime
ENV PYTHONUNBUFFERED=1
ENV DRY_RUN=true

CMD ["python", "main.py"]
