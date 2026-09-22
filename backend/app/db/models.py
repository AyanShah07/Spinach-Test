"""SQLAlchemy 2.0 async models matching the flexible data model in the spec."""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = tuple(
        Index(f"ix_customers_{channel}_eligibility", f"{channel}_opt_in", "has_converted", "last_active", "id")
        for channel in ("email", "sms", "whatsapp", "push")
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    push_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    last_active: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    has_converted: Mapped[bool] = mapped_column(Boolean, default=False)

    events: Mapped[list["Event"]] = relationship(back_populates="customer")
    engagement: Mapped[Optional["EngagementScore"]] = relationship(back_populates="customer", uselist=False)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_customer_channel_type_time", "customer_id", "channel", "event_type", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("customers.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)  # pending|processed|failed

    customer: Mapped["Customer"] = relationship(back_populates="events")


class EngagementScore(Base):
    __tablename__ = "engagement_scores"

    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("customers.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channel_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

    customer: Mapped["Customer"] = relationship(back_populates="engagement")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    objective: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft|active|paused|completed
    audience_size: Mapped[int] = mapped_column(Integer, default=0)


class CampaignMetric(Base):
    __tablename__ = "campaign_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String(64), ForeignKey("campaigns.id"), index=True)
    metric_name: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DLQEvent(Base):
    __tablename__ = "dlq_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    failure_reason: Mapped[str] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    replayed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventOutbox(Base):
    """
    Transactional outbox — written in the SAME transaction as the event row.
    Reconciler publishes to Redis Streams; retention cleanup bounds published rows.

    PRINCIPAL NOTE: commit+XADD cannot be atomic across two systems. Outbox
    makes "committed but unpublished" a queryable, repairable state.
    """
    __tablename__ = "event_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
