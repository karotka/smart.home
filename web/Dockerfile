FROM balenalib/raspberrypi4-64-debian-python:latest
WORKDIR /root/project
COPY requirements.txt requirements.txt
COPY debian-requirements.runtime.txt debian-requirements.runtime.txt

RUN     apt-get update \
    &&  if [ -f "debian-requirements.runtime.txt" ]; then xargs -r -a debian-requirements.runtime.txt apt-get install -y; fi \
    &&  pip install -U \
          pip \
          setuptools \
    &&  pip install -r requirements.txt \
    &&  if [ -f "debian-requirements.build.txt" ]; then xargs -r -a debian-requirements.build.txt apt-get install -y; fi \
    &&  if [ -f "debian-requirements.build.txt" ]; then xargs -r -a debian-requirements.build.txt apt-get -y remove --auto-remove; fi

RUN ln -s /usr/bin/python3 /usr/bin/python 

EXPOSE 8000
COPY . .

CMD python -m tornado.autoreload `pwd`/server.py
