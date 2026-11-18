import threading
import time
from unittest.mock import MagicMock

import pytest

from commons.remote import errors
from commons.remote.connections import ConnectionManager

HOST_KEY = "ssh://user@cluster:22"


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(ConnectionManager, "connections", {})
    monkeypatch.setattr(ConnectionManager, "_host_locks", {})
    monkeypatch.setattr(ConnectionManager, "_closer", None)
    monkeypatch.setattr(ConnectionManager, "_connected_listeners", [])
    monkeypatch.setattr(ConnectionManager, "_disconnected", set())
    return ConnectionManager


@pytest.fixture
def host():
    host = MagicMock()
    host.get_key.return_value = HOST_KEY
    host.server_name.return_value = "cluster"
    return host


def live_client():
    client = MagicMock()
    client.is_alive.return_value = True
    return client


def dead_client():
    client = MagicMock()
    client.is_alive.return_value = False
    return client


def test_live_cached_client_is_reused(manager, host):
    cached = live_client()
    manager.connections[HOST_KEY] = cached

    assert manager.connect(host) is cached
    host.connect.assert_not_called()


def test_dead_cached_client_is_replaced(manager, host):
    """A client killed by a laptop sleep or a VPN drop used to be handed out
    anyway; it failed on the next command and the job was reported as newly
    disconnected even though the host was reachable."""
    stale = dead_client()
    manager.connections[HOST_KEY] = stale
    fresh = live_client()
    host.connect.return_value = fresh

    assert manager.connect(host) is fresh
    stale.close.assert_called_once()
    assert manager.connections[HOST_KEY] is fresh


def test_check_host_is_true_for_a_cached_client(manager, host):
    manager.connections[HOST_KEY] = live_client()

    assert manager.check_host(host) is True


def test_check_host_is_false_without_a_cached_client(manager, host):
    assert manager.check_host(host) is False


def test_check_host_does_not_touch_the_client(manager, host):
    """It runs on the UI thread, once per job row per second, while the client
    belongs to the monitor thread -- which may be closing or replacing it right
    then. A stale 'connected' costs nothing: the next poll goes through
    connect(), which does probe and swaps a dead client out."""
    cached = dead_client()
    manager.connections[HOST_KEY] = cached

    assert manager.check_host(host) is True
    cached.is_alive.assert_not_called()


def test_client_without_liveness_check_is_assumed_usable(manager, host):
    """Not every protocol client implements is_alive; a wrong 'dead' verdict
    would drop a working connection on every poll."""
    cached = MagicMock(spec=["close"])
    manager.connections[HOST_KEY] = cached

    assert manager.connect(host) is cached


def test_failing_liveness_check_is_treated_as_dead(manager, host):
    cached = MagicMock()
    cached.is_alive.side_effect = OSError("transport gone")
    manager.connections[HOST_KEY] = cached
    fresh = live_client()
    host.connect.return_value = fresh

    assert manager.connect(host) is fresh


def test_prune_evicts_and_closes_a_closed_connection(manager, host):
    """connect() only swaps out the client of the host it is asked for, so a
    connection the server closed stayed cached once its jobs stopped polling,
    and check_host() kept calling the host connected."""
    closed = dead_client()
    manager.connections[HOST_KEY] = closed

    manager.prune_closed()

    assert manager.check_host(host) is False
    closed.close.assert_called_once()


def test_prune_keeps_a_live_connection(manager, host):
    cached = live_client()
    manager.connections[HOST_KEY] = cached

    manager.prune_closed()

    assert manager.connections[HOST_KEY] is cached
    cached.close.assert_not_called()


def test_prune_keeps_a_client_without_liveness_check(manager, host):
    cached = MagicMock(spec=["close"])
    manager.connections[HOST_KEY] = cached

    manager.prune_closed()

    assert manager.connections[HOST_KEY] is cached


def test_prune_leaves_a_host_being_connected_alone(manager, host):
    """The connect() holding the lock does its own swap; waiting for it would
    stall the monitor thread behind a handshake."""
    closed = dead_client()
    manager.connections[HOST_KEY] = closed

    with manager._lock_for(HOST_KEY):
        manager.prune_closed()

    assert manager.connections[HOST_KEY] is closed
    closed.close.assert_not_called()


def test_prune_skips_empty_entries(manager, host):
    manager.connections[HOST_KEY] = None

    manager.prune_closed()

    assert HOST_KEY in manager.connections


def drop_dead_client_through_connect(manager, host, client):
    manager.connections[HOST_KEY] = client
    client.is_alive.return_value = False
    host.connect.return_value = live_client()
    manager.connect(host)


def drop_through_drop_client(manager, host, client):
    manager.connections[HOST_KEY] = client
    manager.drop_client(host)


def drop_through_prune(manager, host, client):
    manager.connections[HOST_KEY] = client
    client.is_alive.return_value = False
    manager.prune_closed()


@pytest.mark.parametrize(
    "drop",
    [drop_dead_client_through_connect, drop_through_drop_client, drop_through_prune],
    ids=["connect", "drop_client", "prune"],
)
def test_a_registered_closer_does_every_close(manager, host, drop):
    """The client leaves the cache on the calling thread, which may be the UI
    thread; close() is a paramiko call, so it goes to the monitor thread."""
    closer = MagicMock()
    manager.set_closer(closer)
    client = live_client()

    drop(manager, host, client)

    assert manager.connections.get(HOST_KEY) is not client
    closer.assert_called_once_with(HOST_KEY, client)
    client.close.assert_not_called()


def test_close_now_survives_a_failing_close(manager):
    client = MagicMock()
    client.close.side_effect = OSError("socket already gone")

    manager.close_now(HOST_KEY, client)

    client.close.assert_called_once()


def test_announce_connected_runs_every_listener(manager, host):
    failing = MagicMock(side_effect=RuntimeError("loader broke"))
    listener = MagicMock()
    manager.add_connected_listener(failing)
    manager.add_connected_listener(listener)

    manager.announce_connected(host)

    listener.assert_called_once_with(host)


def test_announce_connected_does_not_connect(manager, host):
    """It runs on the main thread; connecting is the monitor thread's job."""
    manager.announce_connected(host)

    host.connect.assert_not_called()


def test_disconnect_drops_and_closes_the_cached_client(manager, host):
    cached = live_client()
    manager.connections[HOST_KEY] = cached

    manager.disconnect(host)

    assert manager.check_host(host) is False
    cached.close.assert_called_once()


def test_disconnect_keeps_the_stored_credential(manager, host):
    """Connecting again should not need the password to be typed again."""
    manager.connections[HOST_KEY] = live_client()

    manager.disconnect(host)

    host.delete_password.assert_not_called()


def test_polling_does_not_reconnect_a_disconnected_host(manager, host):
    """Dropping the client alone did not last: the next poll reconnected with
    the stored credential a few seconds later."""
    manager.disconnect(host)

    with pytest.raises(errors.UserDisconnectedError):
        manager.connect(host)

    host.connect.assert_not_called()
    assert manager.check_host(host) is False


def test_user_connect_lifts_the_disconnect(manager, host):
    fresh = live_client()
    host.connect.return_value = fresh
    manager.disconnect(host)

    assert manager.connect(host, user_initiated=True) is fresh
    # From then on the job monitor may use it again.
    assert manager.connect(host) is fresh
    host.connect.assert_called_once()


def test_disconnect_only_affects_its_host(manager, host):
    other = MagicMock()
    other.get_key.return_value = "ssh://user@other:22"
    other_client = live_client()
    manager.connections["ssh://user@other:22"] = other_client

    manager.disconnect(host)

    assert manager.connect(other) is other_client


def test_disconnect_during_a_handshake_discards_the_new_client(manager, host):
    """The user clicked Disconnect while the monitor was still shaking hands.
    Caching the client it got would reconnect the host behind their back."""
    fresh = live_client()
    clicked = []

    def handshake():
        # The click comes from the UI thread, which then waits on the host
        # lock this handshake holds.
        clicked.append(threading.Thread(target=manager.disconnect, args=(host,)))
        clicked[0].start()
        deadline = time.monotonic() + 5
        while HOST_KEY not in manager._disconnected and time.monotonic() < deadline:
            time.sleep(0.001)
        return fresh

    host.connect.side_effect = handshake

    with pytest.raises(errors.UserDisconnectedError):
        manager.connect(host)

    clicked[0].join(timeout=5)
    assert not clicked[0].is_alive()
    fresh.close.assert_called_once()
    assert manager.check_host(host) is False


def test_disconnect_closes_through_the_registered_closer(manager, host):
    """Disconnect is clicked on the UI thread; the close is still the monitor's."""
    closer = MagicMock()
    manager.set_closer(closer)
    cached = live_client()
    manager.connections[HOST_KEY] = cached

    manager.disconnect(host)

    closer.assert_called_once_with(HOST_KEY, cached)
    cached.close.assert_not_called()
