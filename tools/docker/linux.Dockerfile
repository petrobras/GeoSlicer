FROM gru.ocir.io/grrjnyzvhu1t/slicerltrace/linux:latest as base

COPY . .

RUN sh ./tools/install_packages.sh

CMD ["sh", "-c", "tail -f /dev/null"]
