import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError, ValidationError
from app.api.responses import success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.alert import Alert
from app.schemas.alert import AlertCreate, AlertResponse

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/", summary="Create a price alert")
async def create_alert(data: AlertCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    if not (0 < data.trigger_price < 1):
        raise ValidationError("trigger_price must be between 0 and 1")

    alert = Alert(
        user_id=user.id,
        market_id=data.market_id,
        outcome=data.outcome,
        condition=data.condition,
        trigger_price=data.trigger_price,
        triggered=False,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    logger.info(f"Alert created: user={user.id} market={data.market_id} {data.condition} {data.trigger_price}")
    return success_response(AlertResponse.model_validate(alert))


@router.get("/", summary="List active alerts")
async def list_alerts(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Alert)
        .where(Alert.user_id == user.id, not Alert.triggered)
        .order_by(Alert.created_at.desc())
    )
    alerts = result.scalars().all()
    return success_response([AlertResponse.model_validate(a) for a in alerts])


@router.delete("/{alert_id}", summary="Delete an alert")
async def delete_alert(alert_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise NotFoundError("Alert not found")

    await db.execute(delete(Alert).where(Alert.id == alert_id))
    await db.commit()
    logger.info(f"Alert deleted: {alert_id} by user={user.id}")
    return success_response({"id": alert_id, "deleted": True})
