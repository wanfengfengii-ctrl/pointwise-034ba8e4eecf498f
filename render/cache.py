from collections import OrderedDict
from threading import Lock


class BlockCache:
    def __init__(self, capacity=64):
        if type(capacity) is not int or capacity < 1:
            raise ValueError('cache capacity must be positive')
        self.capacity = capacity
        self._blocks = OrderedDict()
        self._deferred = set()
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            block = self._blocks.get(key)
            if block is not None:
                self._blocks.move_to_end(key)
            return block

    def put(self, key, samples):
        with self._lock:
            self._blocks[key] = tuple(samples)
            self._blocks.move_to_end(key)
            while len(self._blocks) > self.capacity:
                self._blocks.popitem(last=False)

    def discard(self, key):
        with self._lock:
            self._blocks.pop(key, None)

    def reclaim(self):
        with self._lock:
            count = len(self._blocks)
            self._blocks.clear()
            return count

    def defer_once(self, revision_id, start, end):
        with self._lock:
            self._deferred.add((revision_id, start, end))

    def take_deferral(self, key):
        with self._lock:
            if key not in self._deferred:
                return False
            self._deferred.remove(key)
            return True
