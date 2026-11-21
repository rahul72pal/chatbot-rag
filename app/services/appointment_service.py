"""Appointment service for creating and managing consultation / booking queries.

Supports saving to both MongoDB and the SQLite 'appointments' table.
Enforces the single-query-per-email rule for each chatbot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import delete, func, select, update

from app.core.logger import logger
from app.db.database import SessionLocal
from app.db.models import Appointment


class AppointmentService:
    def __init__(self, mongo_db: Any = None) -> None:
        self._db = mongo_db
        if mongo_db is not None:
            self._collection = mongo_db["appointments"]
            self._chatbots_collection = mongo_db["chatbots"]
        else:
            self._collection = None
            self._chatbots_collection = None

    async def check_email_exists(self, chatbot_id: str, email: str) -> bool:
        """Check if an appointment query already exists for this email under the chatbot."""
        norm_email = email.strip().lower()
        # 1. Check MongoDB first if available
        if self._collection is not None:
            existing = await self._collection.find_one({
                "chatbot_id": chatbot_id,
                "email": norm_email,
            })
            if existing:
                return True

        # 2. Check SQLite appointments table
        try:
            async with SessionLocal() as db_session:
                stmt = select(func.count(Appointment.id)).where(
                    Appointment.chatbot_id == chatbot_id,
                    func.lower(Appointment.email) == norm_email,
                )
                count = await db_session.scalar(stmt)
                if count and count > 0:
                    return True
        except Exception as sql_err:
            logger.warning(f"[AppointmentService] SQLite check error: {sql_err}")

        return False

    async def create_appointment(
        self,
        chatbot_id: str,
        name: str,
        email: str,
        contact_number: str,
        time: str,
        reason: str,
        status: str = "pending",
    ) -> Dict[str, Any]:
        """Create a new appointment query. Rejects if the email already booked for this chatbot."""
        norm_email = email.strip().lower()

        # Enforce business rule: only one appointment query per email for a given chatbot
        if await self.check_email_exists(chatbot_id, norm_email):
            logger.info(
                f"[AppointmentService] Appointment query rejected: email '{norm_email}' "
                f"already has an active query for chatbot '{chatbot_id}'."
            )
            return {
                "ok": False,
                "exists": True,
                "message": (
                    f"An appointment query has already been submitted for email '{norm_email}'. "
                    "Only one appointment request is permitted per email address."
                ),
            }

        appointment_id = str(uuid4())
        now = datetime.utcnow()

        record: Dict[str, Any] = {
            "id": appointment_id,
            "_id": appointment_id,
            "chatbot_id": chatbot_id,
            "name": name.strip(),
            "email": norm_email,
            "contact_number": contact_number.strip(),
            "time": time.strip(),
            "reason": reason.strip(),
            "status": status,
            "created_at": now,
            "updated_at": now,
        }

        # 1. Insert into MongoDB
        if self._collection is not None:
            try:
                await self._collection.insert_one(record)
            except Exception as mongo_err:
                logger.error(f"[AppointmentService] MongoDB insert failed: {mongo_err}")

        # 2. Insert into SQLite table 'appointments'
        try:
            async with SessionLocal.begin() as db_session:
                sql_record = Appointment(
                    id=appointment_id,
                    chatbot_id=chatbot_id,
                    name=name.strip(),
                    email=norm_email,
                    contact_number=contact_number.strip(),
                    time=time.strip(),
                    reason=reason.strip(),
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
                db_session.add(sql_record)
        except Exception as sql_err:
            logger.error(f"[AppointmentService] SQLite insert failed: {sql_err}")

        clean_record = {k: v for k, v in record.items() if k != "_id"}
        # Format datetime for JSON response
        clean_record["created_at"] = now.isoformat()
        clean_record["updated_at"] = now.isoformat()

        logger.info(
            f"[AppointmentService] Successfully created appointment '{appointment_id}' "
            f"for '{name}' ({norm_email}) under chatbot '{chatbot_id}'."
        )
        return {"ok": True, "exists": False, "appointment": clean_record}

    async def list_appointments(
        self,
        user_id: str,
        chatbot_id: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """List appointments for user's chatbots, optionally filtered by a specific chatbot."""
        # Find all chatbots owned by this user
        owned_chatbots: Dict[str, str] = {}
        if self._chatbots_collection is not None:
            cursor = self._chatbots_collection.find(
                {"user_id": user_id},
                {"_id": 1, "name": 1}
            )
            async for bot in cursor:
                bot_id = str(bot["_id"])
                owned_chatbots[bot_id] = bot.get("name", "Untitled Chatbot")

        if not owned_chatbots:
            return []

        # If specific chatbot requested, verify ownership
        if chatbot_id:
            if chatbot_id not in owned_chatbots:
                return []
            allowed_bot_ids = [chatbot_id]
        else:
            allowed_bot_ids = list(owned_chatbots.keys())

        appointments: List[Dict[str, Any]] = []

        # Query MongoDB
        if self._collection is not None:
            query = {"chatbot_id": {"$in": allowed_bot_ids}}
            cursor = (
                self._collection.find(query)
                .sort("created_at", -1)
                .skip(skip)
                .limit(limit)
            )
            async for doc in cursor:
                doc["id"] = doc.pop("_id", str(doc.get("id", "")))
                doc["chatbot_name"] = owned_chatbots.get(doc.get("chatbot_id"), "Chatbot")
                if isinstance(doc.get("created_at"), datetime):
                    doc["created_at"] = doc["created_at"].isoformat()
                if isinstance(doc.get("updated_at"), datetime):
                    doc["updated_at"] = doc["updated_at"].isoformat()
                appointments.append(doc)
            return appointments

        # Fallback to SQLite
        try:
            async with SessionLocal() as db_session:
                stmt = (
                    select(Appointment)
                    .where(Appointment.chatbot_id.in_(allowed_bot_ids))
                    .order_by(Appointment.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
                results = (await db_session.scalars(stmt)).all()
                for appt in results:
                    appointments.append({
                        "id": appt.id,
                        "chatbot_id": appt.chatbot_id,
                        "chatbot_name": owned_chatbots.get(appt.chatbot_id, "Chatbot"),
                        "name": appt.name,
                        "email": appt.email,
                        "contact_number": appt.contact_number,
                        "time": appt.time,
                        "reason": appt.reason,
                        "status": appt.status,
                        "created_at": appt.created_at.isoformat() if appt.created_at else None,
                        "updated_at": appt.updated_at.isoformat() if appt.updated_at else None,
                    })
        except Exception as sql_err:
            logger.error(f"[AppointmentService] SQLite list error: {sql_err}")

        return appointments

    async def update_status(
        self,
        appointment_id: str,
        new_status: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Update the status of an appointment (pending | confirmed | cancelled | completed)."""
        valid_statuses = {"pending", "confirmed", "cancelled", "completed"}
        if new_status not in valid_statuses:
            return None

        # Verify user owns the chatbot for this appointment
        now = datetime.utcnow()
        if self._collection is not None:
            appt = await self._collection.find_one({"_id": appointment_id})
            if not appt:
                appt = await self._collection.find_one({"id": appointment_id})
            if not appt:
                return None

            cid = appt.get("chatbot_id")
            # Check ownership
            if self._chatbots_collection is not None:
                bot = await self._chatbots_collection.find_one({"_id": cid, "user_id": user_id})
                if not bot:
                    return None

            target_id = appt.get("_id")
            await self._collection.update_one(
                {"_id": target_id},
                {"$set": {"status": new_status, "updated_at": now}}
            )

        # Update SQLite table
        try:
            async with SessionLocal.begin() as db_session:
                await db_session.execute(
                    update(Appointment)
                    .where(Appointment.id == appointment_id)
                    .values(status=new_status, updated_at=now)
                )
        except Exception as sql_err:
            logger.warning(f"[AppointmentService] SQLite update error: {sql_err}")

        return {"id": appointment_id, "status": new_status, "updated_at": now.isoformat()}

    async def delete_appointment(self, appointment_id: str, user_id: str) -> bool:
        """Delete an appointment if the user owns the corresponding chatbot."""
        if self._collection is not None:
            appt = await self._collection.find_one({"_id": appointment_id})
            if not appt:
                appt = await self._collection.find_one({"id": appointment_id})
            if not appt:
                return False

            cid = appt.get("chatbot_id")
            if self._chatbots_collection is not None:
                bot = await self._chatbots_collection.find_one({"_id": cid, "user_id": user_id})
                if not bot:
                    return False

            target_id = appt.get("_id")
            await self._collection.delete_one({"_id": target_id})

        # Delete from SQLite
        try:
            async with SessionLocal.begin() as db_session:
                await db_session.execute(
                    delete(Appointment).where(Appointment.id == appointment_id)
                )
        except Exception as sql_err:
            logger.warning(f"[AppointmentService] SQLite delete error: {sql_err}")

        return True

