"""v0.9.0 Room 12 — the Pantry: the LRU stream cache."""

import os
import time

import pytest

from hearth.stream_cache import StreamCache


@pytest.fixture
def cache(tmp_path):
    # 1 KB cap so eviction rounds are testable with tiny payloads.
    return StreamCache(tmp_path / "pantry", max_bytes=1024)


def test_miss_on_empty_cache(cache):
    assert cache.path_for("abc") is None
    assert cache.has("abc") is False


def test_store_then_hit(cache):
    assert cache.store("abc", b"fire") is not None
    assert cache.has("abc")
    assert cache.path_for("abc").read_bytes() == b"fire"


def test_store_overwrites_same_id(cache):
    cache.store("abc", b"first")
    cache.store("abc", b"second")
    assert cache.path_for("abc").read_bytes() == b"second"


def test_store_rejects_empty_and_bad_ids(cache):
    assert cache.store("", b"data") is None
    assert cache.store("../evil", b"data") is None
    assert cache.store("ok", b"") is None


def test_lru_evicts_coldest_first(tmp_path):
    cache = StreamCache(tmp_path / "pantry", max_bytes=1024 * 1024)  # roomy fill
    for name, size in (("old", 300), ("mid", 300), ("new", 300), ("big", 500)):
        cache.store(name, b"x" * size)   # 1400B total
    cache.max_bytes = 1024               # shrink the Pantry, then trim
    now = time.time()
    for name, age in (("old", 400), ("mid", 300), ("new", 200), ("big", 100)):
        os.utime(cache.root / f"{name}.audio", (now - age, now - age))
    removed = cache.trim(keep="big")
    assert removed == 2              # evict until back under cap
    assert not (cache.root / "old.audio").exists()   # coldest goes first
    assert not (cache.root / "mid.audio").exists()
    assert (cache.root / "new.audio").exists()
    assert (cache.root / "big.audio").exists()       # kept alive


def test_hit_touches_survival(cache):
    cache.store("keepme", b"x" * 400)
    cache.store("other", b"x" * 400)
    now = time.time()
    os.utime(cache.root / "keepme.audio", (now - 100, now - 100))
    os.utime(cache.root / "other.audio", (now - 50, now - 50))
    assert cache.path_for("keepme") is not None  # a play — touch lifts it to now
    cache.store("big", b"x" * 600)               # forces a trim round
    assert cache.has("keepme")                   # freshly touched, survives
    assert not cache.has("other")                # the coldest paid the bill


def test_trim_honors_cap(cache):
    for i in range(8):
        cache.store(f"t{i}", b"x" * 200)   # 8 × 200B > 1KB cap
    assert cache.size() <= 1024


def test_clear_is_a_full_broom(cache):
    cache.store("a", b"12345")
    cache.store("b", b"12345")
    removed = cache.clear()
    assert removed == 2
    assert cache.item_count() == 0
    assert cache.size() == 0


def test_broken_root_never_raises(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    cache = StreamCache(blocker / "pantry", max_bytes=64)
    assert cache.store("a", b"data") is None      # mkdir under a file fails
    assert cache.path_for("a") is None
    assert cache.clear() == 0
    assert cache.size() == 0


def test_zero_data_and_zero_limit(cache):
    cache.store("a", b"data")
    assert StreamCache(cache.root, max_bytes=1).trim() >= 1
