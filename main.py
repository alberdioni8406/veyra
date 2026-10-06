"""
MULTIVERSE V0 - Rentable Social Spaces
Economic layer for human connection. BCH payments.
"""
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from database import get_db, init_db
from models import (
    User, Room, RoomParticipant, Payment, Connection, RoomMessage,
    RoomStatus, RoomType, RoomVisibility, PaymentType, PaymentStatus, PlatformConfig
)
from schemas import (
    UserCreate, UserLogin, UserOut, ProfileUpdate, RoomCreate,
    MessageCreate, PlatformStats
)
from auth import (
    get_password_hash, verify_password, create_access_token,
    get_current_user, require_user, require_admin, decode_token
)
from services.payment import payment_engine, Currency
from config import economic_config, DURATION_OPTIONS, CAPACITY_OPTIONS, CATEGORIES

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = next(get_db())
    try:
        if db.query(User).count() == 0:
            admin = User(
                username="admin",
                hashed_password=get_password_hash("admin123"),
                display_name="Platform Admin",
                is_admin=True,
                language="en"
            )
            db.add(admin)
            db.commit()
            print("Seeded admin: admin / admin123")
        if db.query(PlatformConfig).count() == 0:
            for k, v in [
                ("PLATFORM_ROOM_FEE_PERCENT", str(economic_config.PLATFORM_ROOM_FEE_PERCENT)),
                ("MINIMUM_ROOM_PRICE", str(economic_config.MINIMUM_ROOM_PRICE)),
            ]:
                db.add(PlatformConfig(key=k, value=v))
            db.commit()
    finally:
        db.close()
    yield

app = FastAPI(title="Multiverse", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

class ConnectionManager:
    def __init__(self):
        self.room_connections: Dict[int, Dict[int, WebSocket]] = {}

    async def connect(self, room_id: int, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.room_connections:
            self.room_connections[room_id] = {}
        self.room_connections[room_id][user_id] = websocket

    def disconnect(self, room_id: int, user_id: int):
        if room_id in self.room_connections:
            self.room_connections[room_id].pop(user_id, None)
            if not self.room_connections[room_id]:
                del self.room_connections[room_id]

    async def broadcast(self, room_id: int, message: dict, exclude_user: Optional[int] = None):
        if room_id not in self.room_connections:
            return
        dead = []
        for uid, ws in list(self.room_connections[room_id].items()):
            if exclude_user and uid == exclude_user:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(room_id, uid)

manager = ConnectionManager()

def calc_rental_price(duration_minutes: int, capacity: int) -> float:
    hours = duration_minutes / 60.0
    base = economic_config.BASE_RENTAL_PER_HOUR * hours
    if capacity > 100:
        base *= 1.5
    elif capacity > 50:
        base *= 1.2
    return max(round(base, 8), economic_config.MINIMUM_ROOM_PRICE)

def room_to_out(room: Room, db: Session) -> dict:
    now = datetime.now(timezone.utc)
    participant_count = db.query(RoomParticipant).filter(
        RoomParticipant.room_id == room.id, RoomParticipant.left_at.is_(None)
    ).count()
    remaining = None
    if room.expires_at:
        exp = room.expires_at if room.expires_at.tzinfo else room.expires_at.replace(tzinfo=timezone.utc)
        remaining = max(0, int((exp - now).total_seconds()))
    host_username = room.host.username if room.host else None
    return {
        "id": room.id, "name": room.name, "description": room.description,
        "category": room.category,
        "type": room.type.value if hasattr(room.type, "value") else str(room.type),
        "capacity": room.capacity, "entry_price": room.entry_price,
        "rental_price": room.rental_price, "currency": room.currency,
        "status": room.status.value if hasattr(room.status, "value") else str(room.status),
        "visibility": room.visibility.value if hasattr(room.visibility, "value") else str(room.visibility),
        "language": room.language, "country": room.country,
        "starts_at": room.starts_at.isoformat() if room.starts_at else None,
        "expires_at": room.expires_at.isoformat() if room.expires_at else None,
        "created_at": room.created_at.isoformat() if room.created_at else None,
        "host_id": room.host_id, "host_username": host_username,
        "participant_count": participant_count,
        "total_messages": room.total_messages or 0,
        "invite_code": room.invite_code,
        "time_remaining_seconds": remaining,
        "total_entry_revenue": room.total_entry_revenue or 0.0,
    }

def update_room_status(room: Room, db: Session):
    now = datetime.now(timezone.utc)
    exp = room.expires_at if room.expires_at.tzinfo else room.expires_at.replace(tzinfo=timezone.utc)
    if room.status in (RoomStatus.CLOSED, RoomStatus.ARCHIVED):
        return
    if now >= exp:
        room.status = RoomStatus.CLOSED
        room.closed_at = now
        db.commit()
    elif (exp - now).total_seconds() < 300:
        if room.status != RoomStatus.EXPIRING:
            room.status = RoomStatus.EXPIRING
            db.commit()
    elif room.status in (RoomStatus.CREATED, RoomStatus.READY):
        room.status = RoomStatus.LIVE
        if not room.starts_at:
            room.starts_at = now
        db.commit()

# Auth
@app.post("/api/auth/register")
async def register(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username taken")
    user = User(
        username=data.username,
        hashed_password=get_password_hash(data.password),
        display_name=data.display_name or data.username,
        email=data.email, country=data.country, language=data.language,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": UserOut.model_validate(user)}

@app.post("/api/auth/login")
async def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": UserOut.model_validate(user)}

@app.get("/api/me")
async def me(user: User = Depends(require_user)):
    return UserOut.model_validate(user)

@app.patch("/api/me")
async def update_profile(data: ProfileUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)

# Discovery
@app.get("/api/rooms/live")
async def live_rooms(
    category: Optional[str] = None, language: Optional[str] = None,
    country: Optional[str] = None, free_only: bool = False,
    sort: str = "popular", limit: int = 50, db: Session = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    q = db.query(Room).filter(
        Room.visibility == RoomVisibility.PUBLIC,
        Room.status.in_([RoomStatus.LIVE, RoomStatus.READY, RoomStatus.EXPIRING, RoomStatus.CREATED]),
        Room.expires_at > now
    )
    if category:
        q = q.filter(Room.category == category)
    if language:
        q = q.filter(Room.language == language)
    if country:
        q = q.filter(Room.country == country)
    if free_only:
        q = q.filter(Room.entry_price == 0)
    rooms = q.order_by(Room.created_at.desc()).limit(200).all()
    for r in rooms:
        update_room_status(r, db)
    rooms = [r for r in rooms if r.status in (RoomStatus.LIVE, RoomStatus.READY, RoomStatus.EXPIRING)]
    results = [room_to_out(r, db) for r in rooms]
    if sort == "popular":
        results.sort(key=lambda x: x["participant_count"], reverse=True)
    elif sort == "ending":
        results.sort(key=lambda x: x["time_remaining_seconds"] or 999999)
    return results[:limit]

@app.get("/api/rooms/{room_id}")
async def get_room(room_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")
    update_room_status(room, db)
    data = room_to_out(room, db)
    is_participant = False
    is_host = False
    if user:
        part = db.query(RoomParticipant).filter(
            RoomParticipant.room_id == room_id, RoomParticipant.user_id == user.id, RoomParticipant.left_at.is_(None)
        ).first()
        is_participant = part is not None
        is_host = room.host_id == user.id
    data["is_participant"] = is_participant
    data["is_host"] = is_host
    return data

# Rent
@app.post("/api/rooms/rent")
async def rent_space(data: RoomCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    rental_price = calc_rental_price(data.duration_minutes, data.capacity)
    invite = secrets.token_urlsafe(12) if data.visibility.value == "private" else None
    expires = datetime.now(timezone.utc) + timedelta(minutes=data.duration_minutes)
    room = Room(
        host_id=user.id, name=data.name, description=data.description,
        category=data.category,
        type=RoomType.TEXT if data.type.value == "text" else RoomType.VOICE,
        capacity=data.capacity, entry_price=data.entry_price, rental_price=rental_price,
        currency="BCH", expires_at=expires, status=RoomStatus.CREATED,
        visibility=RoomVisibility.PUBLIC if data.visibility.value == "public" else RoomVisibility.PRIVATE,
        language=data.language, country=data.country, invite_code=invite,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    memo = f"rent-{room.id}-{user.id}"
    pay_req = await payment_engine.create_payment(rental_price, Currency.BCH, memo)
    payment = Payment(
        user_id=user.id, room_id=room.id, type=PaymentType.ROOM_RENTAL,
        currency="BCH", amount=pay_req.amount, address=pay_req.address,
        memo=pay_req.memo, status=PaymentStatus.PENDING, expires_at=pay_req.expires_at,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {
        "room": room_to_out(room, db),
        "payment": {
            "id": payment.id, "amount": payment.amount, "currency": payment.currency,
            "address": payment.address, "memo": payment.memo, "status": payment.status.value,
            "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
        },
        "message": "Send exact BCH amount. Verification is automatic (set PAYMENT_TEST_MODE=true for local testing)."
    }

@app.post("/api/payments/{payment_id}/verify")
async def verify_payment_endpoint(payment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.user_id == user.id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")
    if payment.status == PaymentStatus.CONFIRMED:
        return {"status": "already_confirmed", "payment_id": payment.id, "transaction_id": payment.transaction_id}
    result = await payment_engine.verify_payment(
        Currency.BCH, payment.address, payment.amount, payment.memo or "", payment.created_at
    )
    if result.confirmed:
        payment.status = PaymentStatus.CONFIRMED
        payment.transaction_id = result.transaction_id
        payment.confirmed_at = datetime.now(timezone.utc)
        db.commit()
        if payment.type == PaymentType.ROOM_RENTAL and payment.room_id:
            room = db.query(Room).filter(Room.id == payment.room_id).first()
            if room:
                room.status = RoomStatus.LIVE
                room.starts_at = datetime.now(timezone.utc)
                if not db.query(RoomParticipant).filter(RoomParticipant.room_id == room.id, RoomParticipant.user_id == user.id).first():
                    db.add(RoomParticipant(room_id=room.id, user_id=user.id, payment_id=payment.id, is_host=True))
                db.commit()
        return {"status": "confirmed", "transaction_id": result.transaction_id}
    return {"status": "pending", "error": result.error}

# Join
@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")
    update_room_status(room, db)
    if room.status not in (RoomStatus.LIVE, RoomStatus.READY, RoomStatus.EXPIRING):
        raise HTTPException(400, f"Room is {room.status.value}")
    current = db.query(RoomParticipant).filter(RoomParticipant.room_id == room_id, RoomParticipant.left_at.is_(None)).count()
    if current >= room.capacity:
        raise HTTPException(400, "Room is full")
    existing = db.query(RoomParticipant).filter(
        RoomParticipant.room_id == room_id, RoomParticipant.user_id == user.id, RoomParticipant.left_at.is_(None)
    ).first()
    if existing:
        return {"status": "already_joined", "room": room_to_out(room, db)}
    if room.entry_price > 0:
        memo = f"entry-{room.id}-{user.id}"
        pay_req = await payment_engine.create_payment(room.entry_price, Currency.BCH, memo)
        payment = Payment(
            user_id=user.id, room_id=room.id, type=PaymentType.ENTRY_FEE,
            currency="BCH", amount=pay_req.amount, address=pay_req.address,
            memo=pay_req.memo, status=PaymentStatus.PENDING, expires_at=pay_req.expires_at,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        return {
            "status": "payment_required",
            "payment": {
                "id": payment.id, "amount": payment.amount, "address": payment.address,
                "memo": payment.memo, "currency": "BCH",
                "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
            }
        }
    part = RoomParticipant(room_id=room.id, user_id=user.id)
    db.add(part)
    if current + 1 > (room.peak_participants or 0):
        room.peak_participants = current + 1
    db.commit()
    return {"status": "joined", "room": room_to_out(room, db)}

@app.post("/api/rooms/{room_id}/confirm-entry")
async def confirm_entry(room_id: int, payment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(
        Payment.id == payment_id, Payment.user_id == user.id, Payment.room_id == room_id,
        Payment.type == PaymentType.ENTRY_FEE
    ).first()
    if not payment:
        raise HTTPException(404, "Payment not found")
    if payment.status != PaymentStatus.CONFIRMED:
        result = await payment_engine.verify_payment(Currency.BCH, payment.address, payment.amount, payment.memo or "", payment.created_at)
        if result.confirmed:
            payment.status = PaymentStatus.CONFIRMED
            payment.transaction_id = result.transaction_id
            payment.confirmed_at = datetime.now(timezone.utc)
            db.commit()
        else:
            raise HTTPException(400, "Payment not confirmed yet")
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404)
    update_room_status(room, db)
    if room.status not in (RoomStatus.LIVE, RoomStatus.READY, RoomStatus.EXPIRING):
        raise HTTPException(400, "Room not active")
    current = db.query(RoomParticipant).filter(RoomParticipant.room_id == room_id, RoomParticipant.left_at.is_(None)).count()
    if current >= room.capacity:
        raise HTTPException(400, "Room is full")
    if db.query(RoomParticipant).filter(RoomParticipant.room_id == room_id, RoomParticipant.user_id == user.id, RoomParticipant.left_at.is_(None)).first():
        return {"status": "already_joined"}
    part = RoomParticipant(room_id=room.id, user_id=user.id, payment_id=payment.id)
    db.add(part)
    room.total_entry_revenue = (room.total_entry_revenue or 0) + payment.amount
    if current + 1 > (room.peak_participants or 0):
        room.peak_participants = current + 1
    db.commit()
    return {"status": "joined", "room": room_to_out(room, db)}

@app.post("/api/rooms/{room_id}/leave")
async def leave_room(room_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    part = db.query(RoomParticipant).filter(
        RoomParticipant.room_id == room_id, RoomParticipant.user_id == user.id, RoomParticipant.left_at.is_(None)
    ).first()
    if part:
        part.left_at = datetime.now(timezone.utc)
        db.commit()
    manager.disconnect(room_id, user.id)
    return {"status": "left"}

# Host
@app.get("/api/rooms/{room_id}/dashboard")
async def room_dashboard(room_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.host_id != user.id:
        raise HTTPException(403, "Not the host")
    update_room_status(room, db)
    participants = db.query(RoomParticipant, User).join(User).filter(
        RoomParticipant.room_id == room_id, RoomParticipant.left_at.is_(None)
    ).all()
    return {
        "room": room_to_out(room, db),
        "participants": [
            {"user_id": u.id, "username": u.username, "display_name": u.display_name,
             "joined_at": p.joined_at.isoformat() if p.joined_at else None, "is_muted": p.is_muted}
            for p, u in participants
        ],
        "revenue": room.total_entry_revenue or 0,
        "messages": room.total_messages or 0,
    }

@app.post("/api/rooms/{room_id}/close")
async def close_room(room_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.host_id != user.id:
        raise HTTPException(403, "Not the host")
    room.status = RoomStatus.CLOSED
    room.closed_at = datetime.now(timezone.utc)
    db.commit()
    await manager.broadcast(room_id, {"type": "room_closed", "message": "Host closed the room"})
    return {"status": "closed"}

@app.post("/api/rooms/{room_id}/kick/{target_user_id}")
async def kick_user(room_id: int, target_user_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.host_id != user.id:
        raise HTTPException(403, "Not the host")
    part = db.query(RoomParticipant).filter(
        RoomParticipant.room_id == room_id, RoomParticipant.user_id == target_user_id, RoomParticipant.left_at.is_(None)
    ).first()
    if part:
        part.left_at = datetime.now(timezone.utc)
        db.commit()
        await manager.broadcast(room_id, {"type": "user_kicked", "user_id": target_user_id})
        manager.disconnect(room_id, target_user_id)
    return {"status": "kicked"}

# Messages
@app.get("/api/rooms/{room_id}/messages")
async def get_messages(room_id: int, limit: int = 100, db: Session = Depends(get_db), user: User = Depends(require_user)):
    part = db.query(RoomParticipant).filter(
        RoomParticipant.room_id == room_id, RoomParticipant.user_id == user.id, RoomParticipant.left_at.is_(None)
    ).first()
    room = db.query(Room).filter(Room.id == room_id).first()
    if not part and (not room or room.host_id != user.id):
        raise HTTPException(403, "Not in room")
    msgs = db.query(RoomMessage, User).join(User).filter(RoomMessage.room_id == room_id).order_by(RoomMessage.created_at.desc()).limit(limit).all()
    return [
        {"id": m.id, "room_id": m.room_id, "user_id": m.user_id, "username": u.username,
         "display_name": u.display_name, "content": m.content, "created_at": m.created_at.isoformat()}
        for m, u in reversed(msgs)
    ]

@app.post("/api/rooms/{room_id}/messages")
async def post_message(room_id: int, data: MessageCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    part = db.query(RoomParticipant).filter(
        RoomParticipant.room_id == room_id, RoomParticipant.user_id == user.id, RoomParticipant.left_at.is_(None)
    ).first()
    if not part:
        raise HTTPException(403, "Not in room")
    if part.is_muted:
        raise HTTPException(403, "You are muted")
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or room.status not in (RoomStatus.LIVE, RoomStatus.EXPIRING):
        raise HTTPException(400, "Room not accepting messages")
    msg = RoomMessage(room_id=room_id, user_id=user.id, content=data.content.strip())
    db.add(msg)
    room.total_messages = (room.total_messages or 0) + 1
    db.commit()
    db.refresh(msg)
    payload = {
        "type": "message", "id": msg.id, "room_id": room_id, "user_id": user.id,
        "username": user.username, "display_name": user.display_name,
        "content": msg.content, "created_at": msg.created_at.isoformat()
    }
    await manager.broadcast(room_id, payload)
    return payload

@app.websocket("/ws/rooms/{room_id}")
async def websocket_room(websocket: WebSocket, room_id: int, token: str = Query(...)):
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except Exception:
        await websocket.close(code=4001)
        return
    db = next(get_db())
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.close(code=4001)
            return
        part = db.query(RoomParticipant).filter(
            RoomParticipant.room_id == room_id, RoomParticipant.user_id == user_id, RoomParticipant.left_at.is_(None)
        ).first()
        room = db.query(Room).filter(Room.id == room_id).first()
        if not part and (not room or room.host_id != user_id):
            await websocket.close(code=4003)
            return
        await manager.connect(room_id, user_id, websocket)
        await manager.broadcast(room_id, {"type": "user_joined", "user_id": user_id, "username": user.username}, exclude_user=user_id)
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            manager.disconnect(room_id, user_id)
            await manager.broadcast(room_id, {"type": "user_left", "user_id": user_id, "username": user.username})
    finally:
        db.close()

# Connections
@app.post("/api/rooms/{room_id}/connect/{target_user_id}")
async def connect_user(room_id: int, target_user_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.id == target_user_id:
        raise HTTPException(400, "Cannot connect to self")
    a, b = sorted([user.id, target_user_id])
    existing = db.query(Connection).filter(Connection.user_a_id == a, Connection.user_b_id == b).first()
    if existing:
        return {"status": "already_connected", "connection_id": existing.id}
    conn = Connection(user_a_id=a, user_b_id=b, room_id=room_id)
    db.add(conn)
    room = db.query(Room).filter(Room.id == room_id).first()
    if room:
        room.total_connections = (room.total_connections or 0) + 1
    db.commit()
    return {"status": "connected", "connection_id": conn.id}

@app.get("/api/connections")
async def my_connections(user: User = Depends(require_user), db: Session = Depends(get_db)):
    conns = db.query(Connection).filter(or_(Connection.user_a_id == user.id, Connection.user_b_id == user.id)).all()
    result = []
    for c in conns:
        other_id = c.user_b_id if c.user_a_id == user.id else c.user_a_id
        other = db.query(User).filter(User.id == other_id).first()
        if other:
            result.append({
                "id": c.id, "user_id": other.id, "username": other.username,
                "display_name": other.display_name, "avatar": other.avatar,
                "created_at": c.created_at.isoformat()
            })
    return result

# Admin
@app.get("/api/admin/stats")
async def admin_stats(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    live = db.query(Room).filter(Room.status.in_([RoomStatus.LIVE, RoomStatus.EXPIRING]), Room.expires_at > now).count()
    total_rooms = db.query(Room).count()
    rooms_today = db.query(Room).filter(Room.created_at >= today_start).count()
    active_users = db.query(User).count()
    total_parts = db.query(RoomParticipant).filter(RoomParticipant.left_at.is_(None)).count()
    bch_vol = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(Payment.status == PaymentStatus.CONFIRMED).scalar() or 0.0
    platform_rev = float(bch_vol) * (economic_config.PLATFORM_ROOM_FEE_PERCENT / 100.0) * 0.5
    return PlatformStats(
        live_rooms=live, total_rooms=total_rooms, rooms_today=rooms_today,
        active_users=active_users, online_estimate=total_parts, total_participants=total_parts,
        bch_volume=float(bch_vol), platform_revenue=platform_rev, host_revenue=float(bch_vol) - platform_rev,
        pending_payments=db.query(Payment).filter(Payment.status == PaymentStatus.PENDING).count(),
        confirmed_payments=db.query(Payment).filter(Payment.status == PaymentStatus.CONFIRMED).count(),
    )

@app.get("/api/admin/rooms")
async def admin_rooms(user: User = Depends(require_admin), db: Session = Depends(get_db), limit: int = 50):
    rooms = db.query(Room).order_by(Room.created_at.desc()).limit(limit).all()
    return [room_to_out(r, db) for r in rooms]

@app.post("/api/admin/payments/{payment_id}/force-confirm")
async def force_confirm(payment_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404)
    payment.status = PaymentStatus.CONFIRMED
    payment.transaction_id = payment.transaction_id or f"force-{secrets.token_hex(8)}"
    payment.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    if payment.type == PaymentType.ROOM_RENTAL and payment.room_id:
        room = db.query(Room).filter(Room.id == payment.room_id).first()
        if room and room.status == RoomStatus.CREATED:
            room.status = RoomStatus.LIVE
            room.starts_at = datetime.now(timezone.utc)
            if not db.query(RoomParticipant).filter(RoomParticipant.room_id == room.id, RoomParticipant.user_id == payment.user_id).first():
                db.add(RoomParticipant(room_id=room.id, user_id=payment.user_id, payment_id=payment.id, is_host=True))
            db.commit()
    return {"status": "confirmed"}

# Pages
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/room/{room_id}", response_class=HTMLResponse)
async def room_page(request: Request, room_id: int):
    return templates.TemplateResponse("room.html", {"request": request, "room_id": room_id})

@app.get("/rent", response_class=HTMLResponse)
async def rent_page(request: Request):
    return templates.TemplateResponse("rent.html", {
        "request": request, "categories": CATEGORIES,
        "durations": DURATION_OPTIONS, "capacities": CAPACITY_OPTIONS
    })

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return templates.TemplateResponse("profile.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
