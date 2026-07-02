"""ARGUS ingestion — event bus (Task 45).

Two backends behind one interface, selected by config:
  * KafkaBus  — aiokafka producer/consumer when ARGUS_KAFKA_BROKERS is set
                (topics per db/kafka/topics.yaml; sync wrappers over asyncio)
  * FileBus   — append-only JSONL spool per topic (default). Same envelope,
                fully testable offline, and a sane dev mode: the normalize
                consumer (Task 46) drains it identically.

Envelope (every message on every topic):
  {"topic": ..., "key": ..., "ts": epoch_float, "producer": ..., "payload": {...}}
"""
from __future__ import annotations
import asyncio, json, os, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.copilot.config import get_settings

TOPIC_RAW_GDELT = "ingest.raw.gdelt"
TOPIC_RAW_ACLED = "ingest.raw.acled"
TOPIC_NORMALIZED = "ingest.normalized"
RAW_TOPICS = {"gdelt": TOPIC_RAW_GDELT, "acled": TOPIC_RAW_ACLED}


def envelope(topic: str, key: str | None, payload: dict, producer: str) -> dict:
    return {"topic": topic, "key": key, "ts": time.time(),
            "producer": producer, "payload": payload}


class FileBus:
    """JSONL spool: one file per topic under ARGUS spool dir."""
    backend = "file"

    def __init__(self, root: str | None = None):
        s = get_settings()
        self.root = root or os.path.join(os.path.dirname(s.db), "bus")
        os.makedirs(self.root, exist_ok=True)

    def _path(self, topic: str) -> str:
        return os.path.join(self.root, topic.replace("/", "_") + ".jsonl")

    def publish(self, topic: str, messages: list[dict], key_field: str = "source_id",
                producer: str = "worker") -> int:
        with open(self._path(topic), "a", encoding="utf-8") as f:
            for m in messages:
                env = envelope(topic, str(m.get(key_field) or ""), m, producer)
                f.write(json.dumps(env, default=str) + "\n")
        return len(messages)

    def read(self, topic: str, offset: int = 0, limit: int | None = None) -> list[dict]:
        p = self._path(topic)
        if not os.path.exists(p):
            return []
        out = []
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if limit is not None and len(out) >= limit:
                    break
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def depth(self, topic: str) -> int:
        p = self._path(topic)
        if not os.path.exists(p):
            return 0
        with open(p, encoding="utf-8") as f:
            return sum(1 for ln in f if ln.strip())


class KafkaBus:
    """aiokafka over sync wrappers; requires ARGUS_KAFKA_BROKERS."""
    backend = "kafka"

    def __init__(self, brokers: str):
        self.brokers = brokers

    def publish(self, topic: str, messages: list[dict], key_field: str = "source_id",
                producer: str = "worker") -> int:
        async def _send():
            from aiokafka import AIOKafkaProducer
            prod = AIOKafkaProducer(
                bootstrap_servers=self.brokers,
                value_serializer=lambda v: json.dumps(v, default=str).encode(),
                key_serializer=lambda k: (k or "").encode())
            await prod.start()
            try:
                for m in messages:
                    env = envelope(topic, str(m.get(key_field) or ""), m, producer)
                    await prod.send_and_wait(topic, env, key=env["key"])
            finally:
                await prod.stop()
            return len(messages)
        return asyncio.run(_send())

    def read(self, topic: str, offset: int = 0, limit: int | None = None) -> list[dict]:
        async def _read():
            from aiokafka import AIOKafkaConsumer
            cons = AIOKafkaConsumer(
                topic, bootstrap_servers=self.brokers, auto_offset_reset="earliest",
                enable_auto_commit=False, consumer_timeout_ms=3000,
                value_deserializer=lambda b: json.loads(b.decode()))
            await cons.start()
            out = []
            try:
                async for msg in cons:
                    out.append(msg.value)
                    if limit is not None and len(out) >= limit + offset:
                        break
            finally:
                await cons.stop()
            return out[offset:]
        return asyncio.run(_read())


_BUS = None

def get_bus():
    """Factory: KafkaBus when ARGUS_KAFKA_BROKERS set, else FileBus spool."""
    global _BUS
    if _BUS is None:
        brokers = os.environ.get("ARGUS_KAFKA_BROKERS")
        _BUS = KafkaBus(brokers) if brokers else FileBus()
    return _BUS

def reset_bus():
    global _BUS
    _BUS = None
