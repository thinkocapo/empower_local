FROM python:3.11-slim-bookworm

WORKDIR /src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Serve with gunicorn. DSN / release / environment are provided at runtime
# (see docker-compose.yaml). The app reads them from the environment on boot.
EXPOSE 8080
CMD ["gunicorn", "-b", ":8080", "-w", "2", "--timeout", "60", "src.main:app"]
