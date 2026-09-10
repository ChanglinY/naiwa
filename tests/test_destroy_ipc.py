from __future__ import annotations

import threading
import time

from PySide6.QtCore import QCoreApplication, QObject, Slot

from src.destroy_ipc import (
    MAX_MESSAGE_BYTES,
    PIPE_NAME,
    DestroyIpc,
    DestroyPipeServer,
    send_destroy_path,
)


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_pipe_contract_name() -> None:
    assert PIPE_NAME == r"\\.\pipe\NaiwaDestroy"


def test_pipe_delivers_unicode_path() -> None:
    got: list[str] = []
    delivered = threading.Event()
    server = DestroyPipeServer(lambda path: (got.append(path), delivered.set()))
    server.start()
    try:
        assert server.ready.wait(1), f"pipe error {server.error_code}"
        path = r"C:\Users\奶蛙\Desktop\要销毁.txt"
        assert send_destroy_path(path)
        assert delivered.wait(2)
        assert got == [path]
    finally:
        server.stop()
    assert not server.running


def test_callback_failure_does_not_stop_server() -> None:
    calls: list[str] = []
    delivered = threading.Event()

    def callback(path: str) -> None:
        calls.append(path)
        if len(calls) == 1:
            raise RuntimeError("consumer failed")
        delivered.set()

    server = DestroyPipeServer(callback)
    server.start()
    try:
        assert server.ready.wait(1), f"pipe error {server.error_code}"
        assert send_destroy_path(r"C:\Desktop\first.txt")
        assert _wait_until(lambda: len(calls) == 1)
        assert send_destroy_path(r"C:\Desktop\second.txt")
        assert delivered.wait(2)
        assert calls == [r"C:\Desktop\first.txt", r"C:\Desktop\second.txt"]
    finally:
        server.stop()


def test_server_can_restart_after_clean_stop() -> None:
    delivered = threading.Event()
    server = DestroyPipeServer(lambda _path: delivered.set())
    server.start()
    assert server.ready.wait(1), f"pipe error {server.error_code}"
    server.stop()
    assert not server.running

    server.start()
    try:
        assert server.ready.wait(1), f"pipe error {server.error_code}"
        assert send_destroy_path(r"C:\Desktop\after-restart.txt")
        assert delivered.wait(2)
    finally:
        server.stop()


def test_client_rejects_invalid_or_oversized_messages() -> None:
    assert not send_destroy_path("")
    assert not send_destroy_path("bad\npath")
    assert not send_destroy_path("x" * MAX_MESSAGE_BYTES)


def test_qt_bridge_queues_receiver_to_main_thread() -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    main_thread = threading.get_ident()
    received: list[tuple[str, int]] = []

    class Receiver(QObject):
        @Slot(str)
        def receive(self, path: str) -> None:
            received.append((path, threading.get_ident()))

    receiver = Receiver()
    ipc = DestroyIpc()
    ipc.path_received.connect(receiver.receive)
    ipc.start()
    try:
        assert ipc.ready.wait(1)
        path = r"C:\Desktop\qt.txt"
        assert send_destroy_path(path)
        deadline = time.monotonic() + 2
        while not received and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert received == [(path, main_thread)]
    finally:
        ipc.stop()
