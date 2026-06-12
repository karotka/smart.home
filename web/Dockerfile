FROM python:3.11-slim-bookworm

WORKDIR /root/project

# Build deps for numpy/pandas wheel compilation on armhf (no armv7 wheels for some versions).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
# Pin setuptools to a version that still ships pkg_resources — pandas 1.5
# build_meta + some other sdist builds still depend on it. setuptools 78+
# dropped pkg_resources by default and source builds break.
RUN pip install --no-cache-dir "setuptools<78" \
 && pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

# Source is bind-mounted at /root/project at runtime; the CMD just runs the
# launcher.
CMD ["bash", "/root/project/run.sh"]
