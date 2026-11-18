from commons.utils.recursive_progress import RecursiveProgress


def test_same_weight():
    progress_0 = RecursiveProgress()
    progress_1 = progress_0.create_sub_progress()
    progress_2 = progress_0.create_sub_progress()

    progress_1.set_progress(0.5)
    assert abs(progress_0.get_progress() - 0.25) <= 0.00001

    progress_2.set_progress(0.25)

    assert abs(progress_0.get_progress() - 0.375) <= 0.00001

    assert abs(progress_1.get_progress() - 0.5) <= 0.00001
    assert abs(progress_2.get_progress() - 0.25) <= 0.00001

    progress_1.set_progress(1)
    progress_2.set_progress(1)
    assert abs(progress_0.get_progress() - 1) <= 0.00001


def test_different_weights():
    progress_0 = RecursiveProgress()
    progress_1 = progress_0.create_sub_progress(weight=1)
    progress_2 = progress_0.create_sub_progress(weight=3)

    progress_1.set_progress(1)
    assert abs(progress_0.get_progress() - 0.25) <= 0.00001

    progress_2.set_progress(0.25)
    assert abs(progress_0.get_progress() - 0.4375) <= 0.00001


def test_callback():
    current_value = 0

    def progress_callback(progress):
        nonlocal current_value
        current_value = progress

    progress = RecursiveProgress(callback=progress_callback)
    progress.create_sub_progress(weight=1)
    progress_1 = progress.create_sub_progress(weight=3)
    progress_1_0 = progress_1.create_sub_progress(weight=1)
    progress_1_1 = progress_1.create_sub_progress(weight=1)

    assert abs(current_value - 0) <= 0.00001

    progress_1_0.set_progress(0.2)
    assert abs(current_value - 0.075) <= 0.00001

    progress_1_1.set_progress(0.2)
    assert abs(current_value - 0.15) <= 0.00001
