import sys


class OutputLogger(object):
    def __init__(self):
        self.file = None
        self.mode = None
        self.buffer = ""

    def set_log_file(self, filename, mode="at"):
        assert self.file is None
        self.file = filename
        self.mode = mode
        if self.buffer is not None:
            with open(self.file, self.mode) as f:
                f.write(self.buffer)
                self.buffer = None

    def write(self, data):
        # Do not save tqdm print
        if data.startswith("\r"):
            return
        if self.file is not None:
            with open(self.file, self.mode) as f:
                f.write(data)
        if self.buffer is not None:
            self.buffer += data

    def flush(self):
        if self.file is not None:
            with open(self.file, self.mode) as f:
                f.flush()


class TeeOutputStream(object):
    def __init__(self, child_streams, autoflush=False):
        self.child_streams = child_streams
        self.autoflush = autoflush
        self.buffer = ""

    def write(self, data):
        if data is not None:
            for stream in self.child_streams:
                stream.write(data)
            if self.autoflush:
                self.flush()

    def flush(self):
        for stream in self.child_streams:
            stream.flush()


output_logger = None


def init_output_logging(filename, mode="at"):
    global output_logger
    if output_logger is None:
        output_logger = OutputLogger()
        sys.stdout = TeeOutputStream([sys.stdout, output_logger], autoflush=True)
        sys.stderr = TeeOutputStream([sys.stderr, output_logger], autoflush=True)
        output_logger.set_log_file(filename, mode)


def format_time(seconds):
    s = int(round(seconds))
    if s < 60:
        return "%ds" % (s)
    elif s < 60 * 60:
        return "%dm %02ds" % (s // 60, s % 60)
    elif s < 24 * 60 * 60:
        return "%dh %02dm %02ds" % (s // (60 * 60), (s // 60) % 60, s % 60)
    else:
        return "%dd %02dh %02dm" % (s // (24 * 60 * 60), (s // (60 * 60)) % 24, (s // 60) % 60)
