from sqlalchemy import Column, String, Float, Date, DateTime, JSON
from sqlalchemy.sql import func
from database import Base
import uuid

class MetricData(Base):
    __tablename__ = "metric_data"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, nullable=False)
    metric_key = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    details = Column(JSON)
    collected_at = Column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    api_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
