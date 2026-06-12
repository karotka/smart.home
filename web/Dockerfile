FROM python:3.11-slim-bookworm

WORKDIR /root/project

# Build deps for numpy/pandas wheel compilation on armhf (no armv7 wheels for some versions).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

# Source is bind-mounted at /root/project at runtime; the CMD just runs the
# launcher.
CMD ["bash", "/root/project/run.sh"]
