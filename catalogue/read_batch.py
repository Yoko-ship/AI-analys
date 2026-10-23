"""Request-scoped reuse of read-only source data across executor threads.

A batch ends with the request, so approved corrections and issuer changes are
visible on the next request without relying on a TTL or invalidation hooks.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock

_current = ContextVar('catalogue_read_batch', default=None)


@contextmanager
def scope():
    if _current.get() is not None:
        yield
        return
    token = _current.set(({}, RLock()))
    try:
        yield
    finally:
        _current.reset(token)


def get(key, loader):
    state = _current.get()
    if state is None:
        return loader()
    cache, lock = state
    with lock:
        if key not in cache:
            cache[key] = loader()
        return cache[key]


def securities():
    from securities_catalog import get_securities_map
    return get('issuer_securities', get_securities_map)
