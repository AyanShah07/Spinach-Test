"""EventQueue abstract interface — swap Redis Streams for Kafka later without touching business logic."""
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class EventQueue(ABC):
    @abstractmethod
    async def enqueue(self, customer_id: str, payload: dict[str, Any]) -> str:
        """Publish an event. Partition/key by customer_id for ordered processing."""
        ...

    @abstractmethod
    async def consume(
        self,
        consumer_group: str,
        consumer_name: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, Any]]]:
        """
        Read a batch of messages for the consumer group.
        Returns list of (message_id, payload).
        """
        ...

    async def contains(self, message_id: str) -> bool:
        """Whether a previously published message still exists for recovery."""
        return False

    @abstractmethod
    async def ack(self, consumer_group: str, message_id: str) -> None:
        """Acknowledge successful processing."""
        ...

    @abstractmethod
    async def ensure_group(self, consumer_group: str) -> None:
        """Create the consumer group if it does not exist."""
        ...
