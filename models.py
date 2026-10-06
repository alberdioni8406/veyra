from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Enum as SQLEnum, UniqueConstraint
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from database import Base

class RoomStatus(str, enum.Enum):
    CREATED = "created"
    READY = "ready"
    LIVE = "live"
    EXPIRING = "expiring"
    CLOSED = "closed"
    ARCHIVED = "archived"

class RoomType(str, enum.Enum):
    TEXT = "text"
    VOICE = "voice"

class RoomVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"

class PaymentType(str, enum.Enum):
    ROOM_RENTAL = "room_rental"
    ENTRY_FEE = "entry_fee"
    PLATFORM_FEE = "platform_fee"

class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EXPIRED = "expired"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=True)
    avatar = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    country = Column(String(100), nullable=True)
    language = Column(String(10), default="en")
    interests = Column(Text, nullable=True)  # JSON string
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_active = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    rooms_hosted = relationship("Room", back_populates="host")
    participations = relationship("RoomParticipant", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    messages = relationship("RoomMessage", back_populates="user")

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, index=True)
    type = Column(SQLEnum(RoomType), default=RoomType.TEXT)
    capacity = Column(Integer, default=50)
    entry_price = Column(Float, default=0.0)  # in BCH
    rental_price = Column(Float, nullable=False)  # in BCH
    currency = Column(String(10), default="BCH")
    starts_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    status = Column(SQLEnum(RoomStatus), default=RoomStatus.CREATED, index=True)
    visibility = Column(SQLEnum(RoomVisibility), default=RoomVisibility.PUBLIC)
    language = Column(String(10), default="en")
    country = Column(String(100), nullable=True)
    invite_code = Column(String(32), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)

    # Analytics fields
    total_messages = Column(Integer, default=0)
    peak_participants = Column(Integer, default=0)
    total_connections = Column(Integer, default=0)
    total_entry_revenue = Column(Float, default=0.0)

    host = relationship("User", back_populates="rooms_hosted")
    participants = relationship("RoomParticipant", back_populates="room")
    payments = relationship("Payment", back_populates="room")
    messages = relationship("RoomMessage", back_populates="room")

class RoomParticipant(Base):
    __tablename__ = "room_participants"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_room_user"),)

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    left_at = Column(DateTime, nullable=True)
    is_muted = Column(Boolean, default=False)
    is_host = Column(Boolean, default=False)

    room = relationship("Room", back_populates="participants")
    user = relationship("User", back_populates="participations")
    payment = relationship("Payment")

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    type = Column(SQLEnum(PaymentType), nullable=False)
    currency = Column(String(10), default="BCH")
    amount = Column(Float, nullable=False)
    address = Column(String(100), nullable=False)  # receiving address
    expected_txid = Column(String(100), nullable=True)
    transaction_id = Column(String(100), unique=True, nullable=True, index=True)
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, index=True)
    memo = Column(String(100), nullable=True)  # unique payment identifier
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="payments")
    room = relationship("Room", back_populates="payments")

class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id", name="uq_connection"),)

    id = Column(Integer, primary_key=True, index=True)
    user_a_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_b_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)  # where they connected

class RoomMessage(Base):
    __tablename__ = "room_messages"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    room = relationship("Room", back_populates="messages")
    user = relationship("User", back_populates="messages")

class PlatformConfig(Base):
    __tablename__ = "platform_config"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
