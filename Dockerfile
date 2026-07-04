FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

EXPOSE 5000

ENV FLASK_APP=server/standalone.py

CMD ["python3", "-m", "flask", "run", "--host", "0.0.0.0", "--with-threads"]