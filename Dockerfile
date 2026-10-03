FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

EXPOSE 5000

CMD ["sh", "-c", "python -m flask --app app db upgrade && gunicorn --bind 0.0.0.0:5000 'app:create_app()'"]
