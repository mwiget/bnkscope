"""
Notifications API for user notifications and alerts
"""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from core.errors import NotFoundError, handle_route_errors
from database import get_db
from models import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
# Separate router for WebSocket — cannot use HTTP auth dependencies
ws_router = APIRouter(prefix="/api/notifications", tags=["notifications"])
logger = logging.getLogger(__name__)

# Valid values for severity and category
SEVERITY_VALUES = {"info", "success", "warning", "error", "critical"}
# Maps severity to the legacy "type" field so existing readers still work
_SEVERITY_TO_TYPE = {
    "info": "info",
    "success": "success",
    "warning": "warning",
    "error": "error",
    "critical": "error",  # collapse critical → error for back-compat
}
# Window for deduplication: suppress duplicate (user, dedupe_key) within 1 hour
_DEDUPE_WINDOW = timedelta(hours=1)


class NotificationCreate(BaseModel):
    user: str | None = None
    type: str | None = None
    title: str
    message: str
    resource_type: str | None = None
    resource_id: int | None = None
    severity: str = "info"
    category: str = "general"
    action_url: str | None = None
    dedupe_key: str | None = None
    extra_metadata: dict | None = None


class NotificationResponse(BaseModel):
    id: int
    user: str
    type: str
    title: str
    message: str
    resource_type: str | None
    resource_id: int | None
    is_read: bool
    created_at: datetime
    read_at: datetime | None
    severity: str
    category: str
    action_url: str | None
    dedupe_key: str | None
    extra_metadata: dict | None

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    count: int


class NotificationActionResponse(BaseModel):
    success: bool
    message: str


@router.get("", response_model=list[NotificationResponse])
@handle_route_errors("list notifications")
def get_notifications(
    request: Request,
    user: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
    before_id: int | None = None,
    category: str | None = None,
    severity: str | None = None,
    db: Session = Depends(get_db)
):
    """
    Get notifications for a user.

    Returns a bare list of notifications, newest-first.
    Cursor pagination: pass before_id = last_item.id to fetch older pages.
    Iteration ends when fewer than `limit` rows are returned.

    Args:
        request: HTTP request (used to extract JWT username)
        unread_only: If True, only return unread notifications
        limit: Maximum number of notifications to return
        before_id: Cursor — return only notifications with id < before_id
        category: Optional category filter
        severity: Optional severity filter
    """
    # bnkscope is single-user; notifications are not scoped by owner.
    query = db.query(Notification)

    if unread_only:
        query = query.filter(Notification.is_read == False)  # noqa: E712

    if category is not None:
        query = query.filter(Notification.category == category)

    if severity is not None:
        query = query.filter(Notification.severity == severity)

    if before_id is not None:
        query = query.filter(Notification.id < before_id)

    return query.order_by(desc(Notification.id)).limit(limit).all()


@router.get("/unread-count", response_model=UnreadCountResponse)
@handle_route_errors("get unread count")
def get_unread_count(request: Request, user: str | None = None, db: Session = Depends(get_db)):
    """Get count of unread notifications for a user."""
    count = db.query(Notification).filter(
        Notification.is_read == False  # noqa: E712
    ).count()

    return {"count": count}


@router.patch("/{notification_id}/read", response_model=NotificationActionResponse)
@handle_route_errors("mark notification read")
def mark_notification_read(
    notification_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Mark a notification as read."""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()

    if not notification:
        raise NotFoundError("notification", notification_id)

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        db.commit()

    return {"success": True, "message": "Notification marked as read"}


@router.post("/mark-all-read", response_model=NotificationActionResponse)
@handle_route_errors("mark all read")
def mark_all_read(request: Request, user: str | None = None, db: Session = Depends(get_db)):
    """Mark all notifications as read for a user."""
    notifications = db.query(Notification).filter(
        Notification.is_read == False  # noqa: E712
    ).all()

    for notification in notifications:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)

    db.commit()

    return {"success": True, "message": f"Marked {len(notifications)} notifications as read"}


@router.delete("/{notification_id}", response_model=NotificationActionResponse)
@handle_route_errors("delete notification")
def delete_notification(
    notification_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete a notification."""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()

    if not notification:
        raise NotFoundError("notification", notification_id)

    db.delete(notification)
    db.commit()

    return {"success": True, "message": "Notification deleted"}


@router.post("", response_model=NotificationResponse)
@handle_route_errors("create notification")
def create_notification(
    notification: NotificationCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """Create a new notification (for system use). Applies dedupe if dedupe_key is set."""
    data = notification.model_dump()
    if not data.get("user"):
        data["user"] = "local"

    # Derive the legacy `type` field from severity for back-compat
    severity = data.get("severity", "info")
    data["type"] = data.get("type") or _SEVERITY_TO_TYPE.get(severity, "info")

    # Dedupe: if dedupe_key + user matches an existing unread notification within 1h,
    # update it instead of inserting a duplicate.
    dedupe_key = data.get("dedupe_key")
    if dedupe_key:
        window_start = datetime.now(UTC) - _DEDUPE_WINDOW
        existing = (
            db.query(Notification)
            .filter(
                Notification.user == data["user"],
                Notification.dedupe_key == dedupe_key,
                Notification.is_read == False,  # noqa: E712
                Notification.created_at >= window_start,
            )
            .first()
        )
        if existing:
            existing.message = data["message"]
            existing.title = data["title"]
            existing.created_at = datetime.now(UTC)
            db.commit()
            db.refresh(existing)
            return existing

    db_notification = Notification(**data)
    db.add(db_notification)
    db.commit()
    db.refresh(db_notification)

    return db_notification

