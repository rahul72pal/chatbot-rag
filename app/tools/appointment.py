"""Appointment booking tool for conversational chat and voice agents.

Enforces:
1. Two-step Human-in-the-Loop confirmation (the agent MUST verify all details with the user first).
2. Exactly one appointment query per email address per chatbot.
3. Full persistence to both MongoDB and the SQLite 'appointments' table.
"""

from __future__ import annotations

import re
from typing import Optional

from langchain_core.tools import tool

from app.core.context import current_chatbot_id
from app.core.logger import logger
from app.db.mongodb import db


@tool
async def book_appointment(
    name: str,
    email: str,
    contact_number: str,
    time: str,
    reason: str,
    confirmed: bool = False,
    chatbot_id: Optional[str] = None,
) -> str:
    """Book or schedule an appointment/consultation for a user.

    Use this tool whenever the user wants to book an appointment, schedule a consultation,
    or request a callback/meeting.

    HUMAN-IN-THE-LOOP TWO-STEP WORKFLOW:
    1. FIRST STEP (confirmed=False):
       When gathering details or when all 5 details (name, email, contact_number, time, reason)
       are first collected, call this tool with confirmed=False (default).
       The tool will validate the fields and instruct you to read back the complete details to the
       user to get their explicit confirmation before booking.
    2. SECOND STEP (confirmed=True):
       Only after the user hears the details and explicitly says 'yes', 'confirm', 'book it',
       'proceed', or gives clear affirmative consent, call this tool again with confirmed=True
       to officially save the booking in the database.

    Args:
        name: Full name of the person booking the appointment.
        email: Email address of the user (e.g. 'john@example.com').
        contact_number: Phone / contact number of the user.
        time: Requested date and time (e.g. 'Tomorrow at 3:00 PM', '2026-11-15 10:00 AM').
        reason: Purpose or message for the appointment (e.g. 'Product demo', 'Consultation').
        confirmed: Set to True ONLY AFTER the user explicitly confirms the read-back details.
        chatbot_id: Optional chatbot ID (defaults to current active chatbot context).
    """
    cid = chatbot_id or current_chatbot_id.get(None) or "default"

    # Step 3: Deterministic Normalization (Python)
    from app.core.voice_entity_flow import (
        normalize_name,
        normalize_spoken_email,
        normalize_spoken_phone,
        normalize_time,
        validate_all_entities,
        format_readback_confirmation,
    )

    name_clean = normalize_name(name or "")
    email_clean = normalize_spoken_email(email or "")
    phone_clean = normalize_spoken_phone(contact_number or "")
    time_clean = normalize_time(time or "")
    reason_clean = (reason or "").strip()

    entities_dict = {
        "name": name_clean,
        "email": email_clean,
        "contact_number": phone_clean,
        "phone": phone_clean,
        "time": time_clean,
        "reason": reason_clean,
    }

    # Step 4: Validation (Regex, format and ambiguity checks)
    is_valid, missing_fields, validation_errors = validate_all_entities(entities_dict)

    if missing_fields:
        logger.info(f"[Book Appointment] Missing fields: {missing_fields}")
        return (
            f"MISSING_INFORMATION: Please ask the user to provide the following missing detail(s): "
            f"{', '.join(missing_fields)}."
        )

    if validation_errors:
        logger.info(f"[Book Appointment] Validation errors: {validation_errors}")
        return (
            f"VALIDATION_ERROR: The following information is invalid or incomplete:\n"
            + "\n".join(f"- {err}" for err in validation_errors)
            + "\nPlease ask the user to clarify or correct these details."
        )

    # Lazy-load appointment service
    from app.services.appointment_service import AppointmentService
    service = AppointmentService(mongo_db=db.database if db.client is not None else None)

    # Step 5: User Confirmation (Required - Read back complete normalized value)
    if not confirmed:
        # Check if email is already taken before asking the user to confirm
        already_exists = await service.check_email_exists(chatbot_id=cid, email=email_clean)
        if already_exists:
            return (
                f"APPOINTMENT_EXISTS: An appointment query has already been submitted for email '{email_clean}'. "
                "Only one appointment query is permitted per email address. "
                "Please inform the user that their previous appointment request is already on file and our team will get in touch."
            )

        logger.info(
            f"[Book Appointment] Confirmation required for {name_clean} ({email_clean}) at {time_clean}"
        )
        readback_text = format_readback_confirmation(entities_dict)
        return (
            "CONFIRMATION_REQUIRED: All necessary appointment details are collected, normalized, and validated.\n"
            "You MUST now read back the complete normalized values to the user and ask for their verbal confirmation:\n\n"
            f"{readback_text}\n\n"
            "Do NOT finalize or call book_appointment with confirmed=True until the user explicitly responds with verbal confirmation."
        )

    # Step 6: Tool Execution (Save to database only after confirmation)
    logger.info(
        f"[Book Appointment] Creating confirmed appointment for {name_clean} ({email_clean}) under chatbot {cid}"
    )
    result = await service.create_appointment(
        chatbot_id=cid,
        name=name_clean,
        email=email_clean,
        contact_number=phone_clean,
        time=time_clean,
        reason=reason_clean,
        status="pending",
    )

    if not result.get("ok"):
        # Duplicate email query caught
        return (
            f"APPOINTMENT_EXISTS: {result.get('message')} "
            "Please politely inform the user that their appointment query is already registered in the system."
        )

    appt = result.get("appointment", {})
    return (
        f"APPOINTMENT_SUCCESS: The appointment has been successfully booked and registered in the system!\n"
        f"- Appointment ID: {appt.get('id')}\n"
        f"- Name: {name_clean}\n"
        f"- Email: {email_clean}\n"
        f"- Contact Number: {phone_clean}\n"
        f"- Time: {time_clean}\n"
        f"- Status: Pending\n\n"
        f"Please inform the user warmly that their appointment is successfully booked, their reference has been noted, "
        f"and our team will reach out to them at {phone_clean} or {email_clean}."
    )


@tool
async def check_appointment(
    email: str,
    chatbot_id: Optional[str] = None,
) -> str:
    """Check the status and scheduled details of an existing appointment or consultation booking using the user's email address.

    Use this tool whenever a user asks:
    - 'Can you check my appointment?'
    - 'What is the status of my appointment?'
    - 'Did I book an appointment?'
    - 'When is my meeting scheduled?'
    - 'Check my consultation for user@example.com'
    - Or provides their email to verify or retrieve their booking status.

    Args:
        email: The user's email address (e.g. 'john@example.com' or spoken format 'john dot doe at gmail dot com').
        chatbot_id: Optional chatbot ID context.
    """
    from app.core.voice_entity_flow import normalize_spoken_email
    from app.services.appointment_service import AppointmentService

    email_clean = normalize_spoken_email(email or "")
    if not email_clean or "@" not in email_clean or "." not in email_clean:
        return (
            "INVALID_EMAIL: The email address provided could not be recognized. "
            "Please ask the user to provide their valid email address so I can check their appointment records."
        )

    cid = chatbot_id or current_chatbot_id.get(None) or "default"
    try:
        mongo_db = db.database if db.client is not None else None
    except Exception:
        mongo_db = None
    service = AppointmentService(mongo_db=mongo_db)

    logger.info(f"[Check Appointment] Looking up appointment for email '{email_clean}' under chatbot '{cid}'")
    records = await service.get_appointments_by_email(email=email_clean, chatbot_id=cid)

    # If no records found under the specific chatbot ID, check across all records as fallback
    if not records and cid != "default":
        records = await service.get_appointments_by_email(email=email_clean, chatbot_id=None)

    if not records:
        return (
            f"NO_APPOINTMENT_FOUND: No appointment or consultation query was found for email '{email_clean}'.\n"
            f"Please inform the user politely that there is no scheduled appointment currently on file for '{email_clean}'. "
            f"Ask if they would like you to help them schedule or book a new appointment now."
        )

    # Most recent appointment
    appt = records[0]
    status_label = str(appt.get("status", "pending")).capitalize()
    time_str = appt.get("time", "To be determined")
    reason = appt.get("reason", "General Consultation")
    name = appt.get("name", "Client")
    phone = appt.get("contact_number", "Not provided")
    appt_id = appt.get("id", "N/A")

    return (
        f"APPOINTMENT_FOUND: An appointment record was found for '{email_clean}'!\n"
        f"- Reference ID: {appt_id}\n"
        f"- Client Name: {name}\n"
        f"- Email: {email_clean}\n"
        f"- Contact Phone: {phone}\n"
        f"- Scheduled Date & Time: {time_str}\n"
        f"- Purpose / Topic: {reason}\n"
        f"- Current Status: {status_label}\n\n"
        f"Please explain these details warmly and naturally to the user. "
        f"Let them know their appointment status is currently '{status_label}' for '{time_str}', and "
        f"confirm if there is anything else they need assistance with."
    )


