"""API router for managing appointment queries in the admin dashboard."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.db.mongodb import db
from app.services.appointment_service import AppointmentService

router = APIRouter(prefix="/appointments", tags=["Appointments Management"])


def _get_appointment_service() -> AppointmentService:
    return AppointmentService(mongo_db=db.database if db.client is not None else None)


class AppointmentStatusUpdate(BaseModel):
    status: str = Field(..., description="New status: pending | confirmed | cancelled | completed")


@router.get(
    "",
    summary="List appointments for user's chatbots",
    description="Retrieve all appointment bookings for chatbots owned by the authenticated user, optionally filtered by chatbot_id.",
)
async def list_appointments(
    chatbot_id: Optional[str] = Query(None, description="Optional chatbot ID to filter by"),
    current_user: dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    service = _get_appointment_service()
    user_id = current_user["id"]
    return await service.list_appointments(user_id=user_id, chatbot_id=chatbot_id)


@router.patch(
    "/{appointment_id}/status",
    summary="Update appointment status",
    description="Update the status of an appointment (e.g. pending -> confirmed, cancelled, completed).",
)
async def update_appointment_status(
    appointment_id: str,
    payload: AppointmentStatusUpdate,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    service = _get_appointment_service()
    user_id = current_user["id"]
    updated = await service.update_status(
        appointment_id=appointment_id,
        new_status=payload.status.lower().strip(),
        user_id=user_id,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found or you do not have permission to modify it."
        )
    return updated


@router.delete(
    "/{appointment_id}",
    summary="Delete an appointment",
    description="Delete an appointment record owned by the authenticated user's chatbot.",
)
async def delete_appointment(
    appointment_id: str,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    service = _get_appointment_service()
    user_id = current_user["id"]
    success = await service.delete_appointment(
        appointment_id=appointment_id,
        user_id=user_id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found or you do not have permission to delete it."
        )
    return {"ok": True, "message": "Appointment deleted successfully."}

