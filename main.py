from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, get_db, Base
from models import MetricData, User
from auth import hash_password, verify_password, create_token, get_current_user
from pydantic import BaseModel
from datetime import date
from typing import List, Optional
import uuid

Base.metadata.create_all(bind=engine)

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
    return {"access_token": token, "token_type": "bearer", "user": {"email": user.email, "full_name": user.full_name}}

@app.post("/api/v1/auth/login")
def login(data: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = create_token(user.id)
    return {"access_token": token, "token_type": "bearer", "user": {"email": user.email, "full_name": user.full_name}}

@app.get("/api/v1/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"email": current_user.email, "full_name": current_user.full_name}

# ─── Метрики endpoints ───
@app.post("/api/v1/agent/push")
def push_metrics(data: PushData, db: Session = Depends(get_db)):
    for m in data.metrics:
        record = MetricData(
            org_id=data.org_id,
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
