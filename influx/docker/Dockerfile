FROM influxdb

WORKDIR /root



COPY requirements.txt requirements.txt
COPY debian-requirements.txt debian-requirements.txt
RUN     apt-get update \
    &&  if [ -f "debian-requirements.txt" ]; then xargs -r -a debian-requirements.txt apt-get install -y; fi

RUN python3 -m venv python_influx

RUN /root/python_influx/bin/pip3 install influxdb-client


