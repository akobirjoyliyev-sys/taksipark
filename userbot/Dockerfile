FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config.py online.py login.py ./
RUN useradd -r bot && chown -R bot /app
USER bot
CMD ["python", "-u", "online.py"]
