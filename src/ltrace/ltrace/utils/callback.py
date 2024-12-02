class Callback(object):
    def __init__(self, on_update=None):
        self.on_update = on_update or (lambda *args, **kwargs: None)
