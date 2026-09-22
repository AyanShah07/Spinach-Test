"""
Kafka adapter stub behind EventQueue.

Resume lists Kafka for event-driven microservices. Production path:
  Redis Streams (demo / free tier) → Kafka (scale).

This module documents the swap contract. Implement fully when a Kafka
cluster is available (confluent-kafka / aiokafka).
"""
from __future__ import annotations

from typing import Any

from app.queue.interface import EventQueue


class KafkaQueue(EventQueue):
    """
    Placeholder — raises NotImplementedError until wired to a cluster.

    Mapping:
      enqueue  → producer.produce(topic, key=customer_id, value=payload)
      consume  → consumer group poll
      ack      → commit offset
      ensure_group → admin create topic + consumer group
    """

    def __init__(self, bootstrap_servers: str, topic: str = "events"):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic

    async def enqueue(self, customer_id: str, payload: dict[str, Any]) -> str:
        raise NotImplementedError(
            "KafkaQueue: wire aiokafka/confluent-kafka here. "
            "Key by customer_id for per-customer ordering partitions."
        )

    async def consume(self, consumer_group: str, consumer_name: str, count: int = 10, block_ms: int = 5000):
        raise NotImplementedError("KafkaQueue.consume not implemented in demo")

    async def ack(self, consumer_group: str, message_id: str) -> None:
        raise NotImplementedError("KafkaQueue.ack not implemented in demo")

    async def ensure_group(self, consumer_group: str) -> None:
        raise NotImplementedError("KafkaQueue.ensure_group not implemented in demo")
