FROM python:3.12-slim
WORKDIR /runner
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 1000 --create-home runner && mkdir -p /run/script-runner && chown runner:runner /run/script-runner
COPY . .
USER runner
CMD ["python", "start.py"]
