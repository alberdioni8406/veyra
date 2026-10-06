from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

class RoomTypeEnum(str, Enum):
    text = "text"
    voice = "voice"

class RoomVisibilityEnum(str, Enum):
    public = "public"
    private = "private"

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    display_name: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    language: str = "en"

class UserLogin(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str]
    avatar: Optional[str]
    bio: Optional[str]
    country: Optional[str]
    language: str
    interests: Optional[str]
    created_at: datetime
    is_admin: bool = False

    class Config:
        from_attributes = True

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    interests: Optional[str] = None

class RoomCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None
    category: str
    type: RoomTypeEnum = RoomTypeEnum.text
    capacity: int = Field(50, ge=2, le=1000)
    entry_price: float = Field(0.0, ge=0)
    duration_minutes: int = Field(60, ge=15, le=10080)  # up to 7 days
    visibility: RoomVisibilityEnum = RoomVisibilityEnum.public
    language: str = "en"
    country: Optional[str] = None

class RoomOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category: str
    type: str
    capacity: int
    entry_price: float
    rental_price: float
    currency: str
    status: str
    visibility: str
    language: str
    country: Optional[str]
    starts_at: Optional[datetime]
    expires_at: datetime
    created_at: datetime
    host_id: int
    host_username: Optional[str] = None
    participant_count: int = 0
    total_messages: int = 0
    invite_code: Optional[str] = None
    time_remaining_seconds: Optional[int] = None

    class Config:
        from_attributes = True

class PaymentOut(BaseModel):
    id: int
    type: str
    amount: float
    currency: str
    address: str
    memo: Optional[str]
    status: str
    created_at: datetime
    expires_at: Optional[datetime]
    transaction_id: Optional[str] = None

    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)

class MessageOut(BaseModel):
    id: int
    room_id: int
    user_id: int
    username: str
    display_name: Optional[str]
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class ConnectionOut(BaseModel):
    id: int
    user_id: int
    username: str
    display_name: Optional[str]
    avatar: Optional[str]
    created_at: datetime

class PlatformStats(BaseModel):
    live_rooms: int
    total_rooms: int
    rooms_today: int
    active_users: int
    online_estimate: int
    total_participants: int
    bch_volume: float
    platform_revenue: float
    host_revenue: float
    pending_payments: int
    confirmed_payments: int
