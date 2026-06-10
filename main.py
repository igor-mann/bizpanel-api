from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, get_db, Base
from models import MetricData, User
from auth import hash_password, verify_password, create_token, get_current_user
from pydantic import BaseModel
from datetime import date
from typing import List, Optional
import uuid
import secrets

Base.metadata.create_all(bind=engine)

from sqlalchemy import text, inspect
with engine.connect() as conn:
    inspector = inspect(engine)
    columns = [c['name'] for c in inspector.get_columns('users')]
    if 'api_key' not in columns:
        conn.execute(text("ALTER TABLE users ADD COLUMN api_key VARCHAR"))
        conn.commit()
    if 'telegram_chat_id' not in columns:
        conn.execute(text("ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR"))
        conn.commit()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth схемы ───
class RegisterSchema(BaseModel):
    email: str
    password: str
    full_name: str

class LoginSchema(BaseModel):
    email: str
    password: str

# ─── Метрики схемы ───
class MetricItem(BaseModel):
    key: str
    value: float
    period_start: date
    period_end: date
    details: Optional[List] = []

class PushData(BaseModel):
    org_id: str
    metrics: List[MetricItem]

# ─── Auth endpoints ───
@app.post("/api/v1/auth/register")
def register(data: RegisterSchema, db: Session = Depends(get_db)):
    if len(data.password) < 8 or len(data.password) > 64:
        raise HTTPException(status_code=400, detail="Пароль должен быть от 8 до 64 символов")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email уже используется")
    user = User(
        id=str(uuid.uuid4()),
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name
    )
    db.add(user)
    db.commit()
    token = create_token(user.id)
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}

@app.post("/api/v1/auth/login")
def login(data: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = create_token(user.id)
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}

@app.get("/api/v1/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email, "full_name": current_user.full_name}

# ─── API Key endpoints ───
@app.post("/api/v1/auth/apikey")
def generate_api_key(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api_key = "bp_" + secrets.token_hex(32)
    current_user.api_key = api_key
    db.commit()
    return {"api_key": api_key}

@app.get("/api/v1/auth/apikey")
def get_api_key(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"api_key": current_user.api_key}

# ─── Вспомогательная функция ───
def get_user_by_api_key(x_api_key: str = Header(None), db: Session = Depends(get_db)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key required")
    user = db.query(User).filter(User.api_key == x_api_key).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user

# ─── Метрики endpoints ───
@app.post("/api/v1/agent/push")
def push_metrics(data: PushData, db: Session = Depends(get_db), _user: User = Depends(get_user_by_api_key)):
    for m in data.metrics:
        record = MetricData(
            org_id=_user.id,
            metric_key=m.key,
            metric_value=m.value,
            period_start=m.period_start,
            period_end=m.period_end,
            details=m.details
        )
        db.add(record)
    db.commit()
    return {"status": "ok", "count": len(data.metrics)}

@app.get("/api/v1/metrics")
def get_metrics(org_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(MetricData)\
        .filter(MetricData.org_id == org_id)\
        .order_by(MetricData.collected_at.desc())\
        .all()
    return rows

import os
import httpx

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def send_telegram(chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

@app.post("/api/v1/telegram/connect")
def telegram_connect(chat_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.telegram_chat_id = chat_id
    db.commit()
    return {"status": "ok"}

@app.post("/api/v1/telegram/test")
async def telegram_test(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram не подключён")
    await send_telegram(current_user.telegram_chat_id, "✅ BizPanel подключён успешно!")
    return {"status": "ok"}

@app.post("/api/v1/telegram/send_summary")
async def send_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram не подключён")
    rows = db.query(MetricData).filter(MetricData.org_id == current_user.id).order_by(MetricData.collected_at.desc()).all()
    latest = {}
    for r in rows:
        if r.metric_key not in latest:
            latest[r.metric_key] = r
    NAMES = {"revenue": "Выручка", "profit": "Прибыль", "receivables": "Дебиторка", "payables": "Кредиторка", "cash": "Деньги", "tax_liability": "Налоги"}
    lines = ["📊 <b>Сводка BizPanel</b>"]
    for key, name in NAMES.items():
        if key in latest:
            v = latest[key].metric_value
            fmt = f"{v/1e9:.1f} млрд" if v >= 1e9 else f"{v/1e6:.1f} млн"
            lines.append(f"{name}: <b>{fmt} сум</b>")
    await send_telegram(current_user.telegram_chat_id, "\n".join(lines))
    return {"status": "ok"}

# ─── Admin endpoints ───
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change_me_in_production")

def verify_admin(x_admin_key: str = Header(None)):
    if not x_admin_key or not secrets.compare_digest(x_admin_key, ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")

@app.get("/api/v1/admin/users")
def admin_users(db: Session = Depends(get_db), _=Depends(verify_admin)):
    users = db.query(User).all()
    return [{"id": u.id, "email": u.email, "full_name": u.full_name, "api_key": u.api_key} for u in users]

@app.post("/api/v1/admin/reset-password")
def admin_reset_password(email: str, new_password: str, db: Session = Depends(get_db), _=Depends(verify_admin)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"status": "ok", "email": email}

@app.delete("/api/v1/admin/delete-user")
def admin_delete_user(email: str, db: Session = Depends(get_db), _=Depends(verify_admin)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    db.delete(user)
    db.commit()
    return {"status": "deleted", "email": email}
