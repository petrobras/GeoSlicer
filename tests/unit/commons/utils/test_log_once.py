from commons.utils.log_once import LogOnce


def test_a_message_is_logged_once():
    logged = []
    logError = LogOnce(logged.append)

    for _ in range(100):
        logError("RuntimeError('boom')")

    assert logged == ["RuntimeError('boom')"]


def test_distinct_messages_are_each_logged():
    logged = []
    logError = LogOnce(logged.append)

    logError("first")
    logError("second")
    logError("first")

    assert logged == ["first", "second"]


def test_reports_whether_it_logged():
    logError = LogOnce(lambda message: None)

    assert logError("first") is True
    assert logError("first") is False


def test_remembers_at_most_capacity_messages():
    """A stream of distinct errors must not grow it forever; the oldest one is
    forgotten first, and may then be logged again."""
    logged = []
    logError = LogOnce(logged.append, capacity=2)

    logError("a")
    logError("b")
    logError("c")  # forgets "a"
    logError("b")  # still remembered
    logError("a")  # forgotten, so logged again

    assert logged == ["a", "b", "c", "a"]
    assert len(logError._logged) == 2
