from __future__ import annotations

import uuid

from src.single_instance import MUTEX_NAME, SingleInstance


def test_uses_contract_mutex_name() -> None:
    assert MUTEX_NAME == r"Local\NaiwaPet.Running"


def test_second_acquire_fails_until_first_closes() -> None:
    name = rf"Local\NaiwaPet.Test.{uuid.uuid4()}"
    first = SingleInstance(name)
    try:
        assert first.acquired
        second = SingleInstance(name)
        assert not second.acquired
        assert second.error_code == 183
        second.close()
    finally:
        first.close()

    third = SingleInstance(name)
    try:
        assert third.acquired
    finally:
        third.close()


def test_close_is_idempotent() -> None:
    instance = SingleInstance(rf"Local\NaiwaPet.Test.{uuid.uuid4()}")
    instance.close()
    instance.close()
    assert not instance.acquired
