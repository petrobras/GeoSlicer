FROM gru.ocir.io/grrjnyzvhu1t/slicerltrace/windows:latest as base

RUN choco install opencv --version=4.5.5 -y

WORKDIR /slicerltrace

COPY ./tests/unit/requirements.txt ./tests/unit/requirements.txt
RUN python -m pip install -r ./tests/unit/requirements.txt

COPY ./tools/pipeline/requirements.txt ./tools/pipeline/requirements.txt
RUN python -m pip install -r ./tools/pipeline/requirements.txt

COPY ./tools/deploy/requirements.txt ./tools/deploy/requirements.txt
RUN python -m pip install -r ./tools/deploy/requirements.txt

COPY ./src/ltrace/requirements.txt ./src/ltrace/requirements.txt
RUN python -m pip install -r ./src/ltrace/requirements.txt

CMD ["cmd", "/c", "ping", "-t", "localhost", ">", "NUL"]
