FROM python:3.10-slim-bullseye
WORKDIR /root/project

COPY requirements.txt requirements.txt
COPY debian-requirements.txt debian-requirements.txt
COPY run.sh run.sh
RUN chmod +x run.sh

RUN pip3 install --no-cache-dir -r requirements.txt

EXPOSE 8000
COPY . .

CMD /root/project/run.sh
