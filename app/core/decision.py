from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

from sqlalchemy.orm import Session

from app.db.models import User, AccessPoint, RoleZonePermission


@dataclass
class DecisionResult:
    decision: str  # "ALLOW" | "DENY" | "UNKNOWN"
    reasons: List[str]


def decide_access_for_user(
    db: Session,
    user: Optional[User],
    access_point: AccessPoint,
) -> DecisionResult:
    """
    RBAC decision:
    - if user is None -> UNKNOWN
    - if user inactive -> DENY
    - if any role has explicit allow to zone -> ALLOW
    - else -> DENY
    """
    if user is None:
        return DecisionResult("UNKNOWN", ["Пользователь не определён (unknown)."])

    if not user.is_active:
        return DecisionResult("DENY", ["Пользователь помечен как неактивный."])

    zone_id = access_point.zone_id

    role_ids = [r.role_id for r in user.roles] if user.roles else []
    if not role_ids:
        return DecisionResult("DENY", ["У пользователя не назначены роли."])

    perms = (
        db.query(RoleZonePermission)
        .filter(RoleZonePermission.role_id.in_(role_ids))
        .filter(RoleZonePermission.zone_id == zone_id)
        .all()
    )

    if not perms:
        return DecisionResult("DENY", ["Нет правил доступа для ролей пользователя в данной зоне."])

    if any(p.is_allowed for p in perms):
        return DecisionResult("ALLOW", ["Есть разрешающее правило для зоны по одной из ролей."])

    return DecisionResult("DENY", ["Все найденные правила для зоны запрещающие."])