FROM python:3.11-slim-bookworm

WORKDIR /root/project

# Build deps for numpy/pandas wheel compilation on armhf (no armv7 wheels for some versions).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
# Pin setuptools to a version that still ships pkg_resources. setuptools
# 78+ dropped pkg_resources, which breaks sdist builds for pandas 1.5 and
# others. PIP_CONSTRAINT applies the cap to the per-package build-isolation
# environments too, not just the main install env.
# pkg_resources lived in setuptools through 79.x — it was removed in 80.0.
# pandas 1.5 (and friends) need it for their sdist build; msgpack 1.2
# requires setuptools>=78.1.1. <80 satisfies both.
RUN echo "setuptools<80" > /root/pip-constraints.txt
ENV PIP_CONSTRAINT=/root/pip-constraints.txt
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

# Source is bind-mounted at /root/project at runtime; the CMD just runs the
# launcher.
CMD ["bash", "/root/project/run.sh"]
