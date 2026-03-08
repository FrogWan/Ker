from pathlib import Path
from ker.gateway.delivery import AsyncDeliveryQueue, chunk_message


def test_enqueue_and_load(tmp_path: Path):
    q = AsyncDeliveryQueue(tmp_path)
    did = q.enqueue("cli", "user", "hello")
    assert did
    pending = q.load_pending()
    assert len(pending) == 1
    assert pending[0].text == "hello"


def test_ack(tmp_path: Path):
    q = AsyncDeliveryQueue(tmp_path)
    did = q.enqueue("cli", "user", "hello")
    q.ack(did)
    assert len(q.load_pending()) == 0


def test_chunk_message_short():
    chunks = chunk_message("hello", 100)
    assert chunks == ["hello"]


def test_chunk_message_long():
    text = "a" * 200
    chunks = chunk_message(text, 50)
    assert len(chunks) > 1
    assert "".join(chunks) == text
