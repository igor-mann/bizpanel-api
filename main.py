from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, get_db, Base
from models import MetricData
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

class MetricItem(BaseModel):
    key: str
    value: float
    period_start: date
    period_end: date
    details: Optional[List] = []

class PushData(BaseModel):
    org_id: str
    metrics: List[MetricItem]

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
def get_metrics(org_id: str, db: Session = Depends(get_db)):
    rows = db.query(MetricData)\
        .filter(MetricData.org_id == org_id)\
        .order_by(MetricData.collected_at.desc())\
        .all()
    return rows