# linkedin/tasks/send_message.py
"""Send Message task — dispatches approved HITL drafted messages via Playwright."""
from __future__ import annotations

import logging

from termcolor import colored

from linkedin.db.deals import get_profile_dict_for_public_id
from linkedin.models import ActionLog
from chat.models import ChatMessage

logger = logging.getLogger(__name__)


def handle_send_message(task, session, qualifiers=None):
    from linkedin.actions.message import send_raw_message
    from linkedin.db.deals import set_profile_state
    from linkedin.enums import ProfileState
    from linkedin.tasks.connect import enqueue_follow_up

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]
    message_id = payload["message_id"]

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 send_message", "blue", attrs=["bold"]), public_id,
    )

    try:
        msg = ChatMessage.objects.get(pk=message_id)
    except ChatMessage.DoesNotExist:
        error_msg = f"send_message: ChatMessage {message_id} no longer exists — aborting"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    profile_dict = get_profile_dict_for_public_id(session, public_id)
    if profile_dict is None:
        raise RuntimeError(f"No Deal found for {public_id}")

    profile = profile_dict.get("profile") or profile_dict

    logger.info("[%s] Dispatching approved message for %s...", session.campaign, public_id)
    sent = send_raw_message(session, profile, msg.content)
    
    if not sent:
        raise RuntimeError("LinkedIn blocked the message delivery (UI failed).")

    # Assuming success, remove draft suffix if it exists, record rate limit actions
    if msg.linkedin_urn.startswith("draft_"):
        msg.linkedin_urn = msg.linkedin_urn.replace("draft_", "sent_")
        msg.save(update_fields=["linkedin_urn"])

    name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip() or public_id
    session.linkedin_profile.record_action(
        ActionLog.ActionType.FOLLOW_UP, 
        session.campaign,
        target_name=name,
        target_public_id=public_id,
        status="success",
        note=f"Message: {msg.content[:50]}..."
    )
    
    # Schedule next follow up in 24 hours (default) since the AI already made a decision prior
    from crm.models.deal import Deal
    deal = Deal.objects.filter(lead__public_identifier=public_id, campaign_id=campaign_id).first()
    enqueue_follow_up(campaign_id, public_id, delay_seconds=24 * 3600, deal=deal)
    logger.info("Message dispatched successfully. Next follow-up delayed 24h.")
