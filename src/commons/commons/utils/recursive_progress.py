class RecursiveProgress:
    def __init__(self, callback=None, weight=1):
        self.callback = callback
        self.weight = weight
        self.progress_list = []
        self.progress_value = 0

    def create_sub_progress(self, weight=1):
        new_progress = RecursiveProgress(self.__subprogress_updated, weight)
        self.progress_list.append(new_progress)
        return new_progress

    def set_progress(self, progress):
        self.progress_value = progress
        if self.callback:
            self.callback(progress)

    def get_progress(self):
        return self.progress_value

    def _get_weight(self):
        return self.weight

    def __update_progress(self):
        weight_sum = 0
        value = 0
        for progress in self.progress_list:
            weight = progress._get_weight()
            value += progress.get_progress() * weight
            weight_sum += weight
        self.set_progress(value / weight_sum)

    def __subprogress_updated(self, _):
        self.__update_progress()
