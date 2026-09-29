from threading import Event

from candidate_screening.worker import serve


def test_worker_drains_batch_then_waits_when_queue_is_empty():
    class Dispatcher:
        def __init__(self):
            self.calls = []

        def run_once(self, limit):
            self.calls.append(limit)
            return {"sent": 2 if len(self.calls) == 1 else 0, "failed": 0, "cancelled": 0}

    class Stop(Event):
        def __init__(self):
            super().__init__()
            self.waits = []

        def wait(self, timeout=None):
            self.waits.append(timeout)
            self.set()
            return True

    dispatcher = Dispatcher()
    stop = Stop()
    serve(dispatcher, stop, interval=0.25, batch_size=2)
    assert dispatcher.calls == [2, 2]
    assert stop.waits == [0.25]
