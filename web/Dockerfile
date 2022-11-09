FROM karotka/pi4-buster-python310
WORKDIR /root/project

COPY requirements.txt requirements.txt
COPY debian-requirements.txt debian-requirements.txt
COPY run.sh run.sh

#RUN cp $HOME/.vimrc .vimrc

#RUN     apt-get update \
#    &&  if [ -f "debian-requirements.txt" ]; then xargs -r -a debian-requirements.txt apt-get install -y; fi
#RUN /usr/local/bin/python -m pip install --upgrade pip

RUN pip3 install -r requirements.txt

EXPOSE 8000
COPY . .

CMD /root/project/run.sh
