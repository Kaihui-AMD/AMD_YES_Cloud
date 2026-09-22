"""Regression check for the LRU implementation generated in the 9B smoke test."""

from collections import OrderedDict
import threading


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = OrderedDict()

    def get(self, key: int) -> int:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return -1

    def put(self, key: int, value: int) -> None:
        if self.capacity == 0:
            return
        if key in self.cache:
            self.cache[key] = value
            return
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


class ThreadSafeLRUCache:
    def __init__(self, capacity: int):
        self._lock = threading.Lock()
        self.cache = LRUCache(capacity)

    def get(self, key: int) -> int:
        with self._lock:
            return self.cache.get(key)

    def put(self, key: int, value: int) -> None:
        with self._lock:
            self.cache.put(key, value)


def main() -> None:
    cache = ThreadSafeLRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    cache.put(1, 10)
    cache.put(3, 3)
    assert cache.get(1) == 10, (
        "Model bug reproduced: updating key 1 did not move it to the MRU position, "
        "so key 1 was evicted when key 3 was inserted."
    )
    assert cache.get(2) == -1, (
        "Key 2 should be the least-recently-used entry after key 1 is updated."
    )


if __name__ == "__main__":
    main()
