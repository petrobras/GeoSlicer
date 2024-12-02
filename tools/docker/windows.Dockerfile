FROM gru.ocir.io/grrjnyzvhu1t/slicerltrace/windows:latest as base

RUN choco install opencv --version=4.5.5 -y

WORKDIR /slicerltrace

COPY ./.git-blame-ignore-revs c:/slicerltrace/.git-blame-ignore-revs
COPY ./.gitattributes c:/slicerltrace/.gitattributes
COPY ./.gitignore c:/slicerltrace/.gitignore
COPY ./.gitmodules c:/slicerltrace/.gitmodules
COPY ./pyproject.toml c:/slicerltrace/pyproject.toml
COPY ./tools c:/slicerltrace/tools

RUN python -m pip install -r c:/slicerltrace/tools/deploy/requirements.txt
RUN python -m pip install -r c:/slicerltrace/tools/pipeline/requirements.txt
RUN python -m pip install -r c:/slicerltrace/tests/unit/requirements.txt
RUN python -m pip install -e c:/slicerltrace/tools

COPY ./src/ltrace/ c:/slicerltrace/src/ltrace/
RUN python -m pip install -e c:/slicerltrace/src/ltrace

COPY ./src/modules/ c:/slicerltrace/src/modules/
RUN python -m pip install -e c:/slicerltrace/src/modules
RUN python -m pip install -r c:/slicerltrace/src/modules/MicrotomRemote/Libs/microtom/requirements.txt

COPY ./src/submodules/ c:/slicerltrace/src/submodules/
RUN python -m pip install -e c:/slicerltrace/src/submodules/porespy
RUN python -m pip install -e c:/slicerltrace/src/submodules/biaep
RUN python -m pip install -e c:/slicerltrace/src/submodules/py_pore_flow

COPY ./tests/ c:/slicerltrace/tests/

CMD ["cmd", "/c", "ping", "-t", "localhost", ">", "NUL"]
