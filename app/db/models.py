from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from flask_login import UserMixin


class Base(DeclarativeBase):
    pass


# --- Администраторы веб-интерфейса ---
class Admin(Base, UserMixin):
    __tablename__ = "admins"

    admin_id = mapped_column(Integer, primary_key=True)
    username = mapped_column(String(64), unique=True, nullable=False)
    password_hash = mapped_column(String(255), nullable=False)
    is_active = mapped_column(Boolean, nullable=False, default=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    def get_id(self):
        return str(self.admin_id)


# --- Пользователи СКУД ---
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles",
        back_populates="users",
        lazy="selectin"
    )
    face_templates: Mapped[list["FaceTemplate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    access_events: Mapped[list["AccessEvent"]] = relationship(back_populates="user")


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list[User]] = relationship(
        secondary="user_roles",
        back_populates="roles",
        lazy="selectin"
    )
    permissions: Mapped[list["RoleZonePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False)


# --- Структура объекта ---
class Zone(Base):
    __tablename__ = "zones"

    zone_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    access_points: Mapped[list["AccessPoint"]] = relationship(back_populates="zone")
    permissions: Mapped[list["RoleZonePermission"]] = relationship(
        back_populates="zone", cascade="all, delete-orphan"
    )


class Camera(Base):
    __tablename__ = "cameras"

    camera_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Тип источника: "webcam" | "rtsp" | "file"
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Для webcam: "0" (индекс), для rtsp/file: URL/путь
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    access_point: Mapped["AccessPoint"] = relationship(back_populates="camera", uselist=False)


class ControlUnit(Base):
    __tablename__ = "control_units"

    control_unit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Например: "stub" | "http"
    unit_type: Mapped[str] = mapped_column(String(32), nullable=False, default="stub")
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    access_points: Mapped[list["AccessPoint"]] = relationship(back_populates="control_unit")


class AccessPoint(Base):
    __tablename__ = "access_points"
    __table_args__ = (
        UniqueConstraint("camera_id", name="uq_access_point_camera"),
    )

    access_point_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.zone_id", ondelete="RESTRICT"), nullable=False)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.camera_id", ondelete="RESTRICT"), nullable=False)
    control_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("control_units.control_unit_id", ondelete="SET NULL"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    zone: Mapped[Zone] = relationship(back_populates="access_points")
    camera: Mapped[Camera] = relationship(back_populates="access_point")
    control_unit: Mapped[ControlUnit | None] = relationship(back_populates="access_points")
    access_events: Mapped[list["AccessEvent"]] = relationship(back_populates="access_point")


class RoleZonePermission(Base):
    __tablename__ = "role_zone_permissions"
    __table_args__ = (UniqueConstraint("role_id", "zone_id", name="uq_role_zone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.zone_id", ondelete="CASCADE"), nullable=False)
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    role: Mapped[Role] = relationship(back_populates="permissions")
    zone: Mapped[Zone] = relationship(back_populates="permissions")


# --- Биометрия и журнал ---
class FaceTemplate(Base):
    __tablename__ = "face_templates"

    template_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="face_templates")


class AccessEvent(Base):
    __tablename__ = "access_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    access_point_id: Mapped[int] = mapped_column(
        ForeignKey("access_points.access_point_id", ondelete="CASCADE"), nullable=False
    )

    # user_id может быть NULL, если unknown/не распознано
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    # "ALLOW" | "DENY" | "UNKNOWN"
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_point: Mapped[AccessPoint] = relationship(back_populates="access_events")
    user: Mapped[User | None] = relationship(back_populates="access_events")