FROM gru.ocir.io/grrjnyzvhu1t/slicerltrace/linux:latest as base

RUN yum -y update ; yum -y install git-lfs

COPY . .

RUN sh ./tools/install_packages.sh

CMD ["sh", "-c", "tail -f /dev/null"]
