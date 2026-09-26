import threading
import time
import unittest

from core.audio.manager import AudioManager


class FakeSpeaker:
    """Blocks for `duration` per utterance, interruptible; tracks overlap."""

    def __init__(self, duration=0.2, fail_on=None):
        self.duration = duration
        self.fail_on = fail_on
        self.spoken = []
        self.interrupted = []
        self.active = 0
        self.max_active = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def speak(self, text):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self._stop.clear()
        try:
            if text == self.fail_on:
                raise RuntimeError("tts exploded")
            if self._stop.wait(self.duration):
                self.interrupted.append(text)
            else:
                self.spoken.append(text)
        finally:
            with self._lock:
                self.active -= 1

    def stop(self):
        self._stop.set()


def manager(policy="queue", duration=0.2, max_queue=5, max_age=30.0, fail_on=None):
    sp = FakeSpeaker(duration, fail_on)
    m = AudioManager({"policy": policy, "max_queue_size": max_queue, "max_age_s": max_age,
                      "shutdown_timeout_s": 2.0}, sp.speak, sp.stop)
    m.start()
    return m, sp


class AudioManagerTest(unittest.TestCase):
    def test_queue_policy_fifo_no_overlap(self):
        m, sp = manager("queue", duration=0.05)
        for t in ("Room 204", "Chair on your left", "Exit"):
            self.assertEqual(m.submit(t), "queued")
        self.assertTrue(m.wait_idle(3))
        self.assertEqual(sp.spoken, ["Room 204", "Chair on your left", "Exit"])
        self.assertEqual(sp.max_active, 1)
        m.shutdown()

    def test_queue_full_drops_oldest(self):
        m, sp = manager("queue", duration=0.3, max_queue=2)
        m.submit("A")
        time.sleep(0.05)  # A is speaking
        for t in ("B", "C", "D"):
            m.submit(t)
        self.assertTrue(m.wait_idle(3))
        self.assertEqual(sp.spoken, ["A", "C", "D"])
        self.assertEqual(m.stats["dropped_full"], 1)
        m.shutdown()

    def test_interrupt_policy(self):
        m, sp = manager("interrupt", duration=1.0)
        m.submit("Room 204")
        time.sleep(0.1)
        self.assertEqual(m.submit("Chair on your left"), "interrupting")
        self.assertTrue(m.wait_idle(3))
        self.assertEqual(sp.interrupted, ["Room 204"])
        self.assertEqual(sp.spoken, ["Chair on your left"])
        self.assertEqual(sp.max_active, 1)
        m.shutdown()

    def test_interrupt_clears_queue(self):
        m, sp = manager("interrupt", duration=0.5)
        m.submit("A")
        time.sleep(0.05)
        m.submit("B")
        m.submit("C")
        self.assertTrue(m.wait_idle(3))
        self.assertEqual(sp.spoken, ["C"])
        m.shutdown()

    def test_drop_if_busy_policy(self):
        m, sp = manager("drop_if_busy", duration=0.3)
        self.assertEqual(m.submit("Room 204"), "queued")
        time.sleep(0.05)
        self.assertEqual(m.submit("Chair on your left"), "dropped_busy")
        self.assertTrue(m.wait_idle(3))
        self.assertEqual(sp.spoken, ["Room 204"])
        m.shutdown()

    def test_stale_requests_dropped(self):
        m, sp = manager("queue", duration=0.4, max_age=0.2)
        m.submit("A")
        time.sleep(0.05)
        m.submit("B")  # waits 0.35 s behind A -> older than 0.2 s
        self.assertTrue(m.wait_idle(3))
        self.assertEqual(sp.spoken, ["A"])
        self.assertEqual(m.stats["dropped_stale"], 1)
        m.shutdown()

    def test_tts_failure_does_not_kill_worker(self):
        m, sp = manager("queue", duration=0.01, fail_on="boom")
        with self.assertLogs("audio", level="ERROR"):
            m.submit("boom")
            m.submit("after")
            self.assertTrue(m.wait_idle(3))
        self.assertEqual(sp.spoken, ["after"])
        self.assertEqual(m.stats["failed"], 1)
        m.shutdown()

    def test_shutdown_stops_speech_and_joins(self):
        m, sp = manager("queue", duration=5.0)
        m.submit("long speech")
        time.sleep(0.05)
        t0 = time.monotonic()
        self.assertTrue(m.shutdown())
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(m.submit("late"), "rejected_stopped")


if __name__ == "__main__":
    unittest.main()
