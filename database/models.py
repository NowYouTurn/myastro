import datetime
import enum
from sqlalchemy import (
    Column, Integer, String, DateTime, Float, Boolean,
    ForeignKey, BigInteger, Text, Enum as SQLAlchemyEnum, Index, select, func
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func as sqlfunc

from database.database import Base # Импортируем Base
from kerykeion import AstrologicalSubject as KrInstance

# --- Enums ---
class PaymentStatus(enum.Enum):
    PENDING = "pending"; WAITING_FOR_CAPTURE = "waiting_for_capture"; SUCCEEDED = "succeeded"; CANCELED = "canceled"
class LogLevel(enum.Enum):
    DEBUG = "DEBUG"; INFO = "INFO"; WARNING = "WARNING"; ERROR = "ERROR"; CRITICAL = "CRITICAL"

# --- Модели ---
class User(Base):
    __tablename__ = 'users'
    id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String, nullable=True, index=True)
    first_name = Column(String, nullable=False); last_name = Column(String, nullable=True)
    language_code = Column(String(10), nullable=True) # Добавили длину
    registration_date = Column(DateTime(timezone=True), server_default=sqlfunc.now(), index=True)
    last_activity_date = Column(DateTime(timezone=True), onupdate=sqlfunc.now(), default=sqlfunc.now, index=True)
    credits = Column(Integer, default=0, nullable=False)
    first_service_used = Column(Boolean, default=False, nullable=False)
    accepted_terms = Column(Boolean, default=False, nullable=False)
    daily_horoscope_time = Column(String(5), nullable=True, index=True) # HH:MM
    referral_code = Column(String, unique=True, index=True, nullable=True)
    referrer_id = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    # Relationships
    referrer = relationship("User", remote_side=[id], backref="referrals")
    natal_data = relationship("NatalData", back_populates="user", uselist=False, cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan", lazy="selectin")
    logs = relationship("Log", back_populates="user", cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (Index('ix_users_accepted_terms', 'accepted_terms'),)
    def __repr__(self): return f"<User(id={self.id})>"

class NatalData(Base):
    __tablename__ = 'natal_data'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    birth_date = Column(String(10), nullable=False) # YYYY-MM-DD
    birth_time = Column(String(5), nullable=False) # HH:MM
    birth_city = Column(String, nullable=False)
    latitude = Column(Float, nullable=False); longitude = Column(Float, nullable=False)
    timezone = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=sqlfunc.now())
    updated_at = Column(DateTime(timezone=True), onupdate=sqlfunc.now(), default=sqlfunc.now)
    user = relationship("User", back_populates="natal_data")
    def __repr__(self): return f"<NatalData(user_id={self.user_id})>"

class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    yookassa_payment_id = Column(String, unique=True, index=True, nullable=False)
    amount = Column(Integer, nullable=False) # Копейки
    currency = Column(String(3), default="RUB", nullable=False)
    credits_purchased = Column(Integer, nullable=False)
    status = Column(SQLAlchemyEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, index=True)
    credits_awarded = Column(Boolean, default=False, nullable=False, index=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=sqlfunc.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=sqlfunc.now(), default=sqlfunc.now)
    user = relationship("User", back_populates="payments")
    def __repr__(self): return f"<Payment(id={self.id}, status={self.status.name})>"

class Log(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=sqlfunc.now(), index=True)
    level = Column(SQLAlchemyEnum(LogLevel), nullable=False, index=True)
    message = Column(Text, nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    handler = Column(String, nullable=True)
    exception_info = Column(Text, nullable=True)
    user = relationship("User", back_populates="logs")
    __table_args__ = (Index('ix_logs_level_timestamp', 'level', 'timestamp'),)
    def __repr__(self): return f"<Log(id={self.id}, level={self.level.name})>"