# linkedin/tasks/follow_up.py
"""Follow-up task — runs the agentic follow-up for one CONNECTED profile."""
from __future__ import annotations

import logging

from termcolor import colored

from linkedin.db.deals import get_profile_dict_for_public_id
from linkedin.models import ActionLog
from linkedin.exceptions import TaskSkipped

logger = logging.getLogger(__name__)


def handle_follow_up(task, session, qualifiers):
    from linkedin.actions.message import send_raw_message
    from linkedin.agents.follow_up import run_follow_up_agent
    from linkedin.db.deals import set_profile_state
    from linkedin.enums import ProfileState
    from linkedin.tasks.connect import enqueue_follow_up, _seconds_until_tomorrow

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 follow_up", "green", attrs=["bold"]), public_id,
    )

    # Rate limit check
    if not session.linkedin_profile.can_execute(ActionLog.ActionType.FOLLOW_UP):
        from crm.models.deal import Deal
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        enqueue_follow_up(campaign_id, public_id, delay_seconds=_seconds_until_tomorrow(), deal=deal)
        raise TaskSkipped("Daily follow-up limit reached")

    profile_dict = get_profile_dict_for_public_id(session, public_id)
    if profile_dict is None:
        error_msg = f"follow_up: no Deal for {public_id} — aborting"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    profile = profile_dict.get("profile") or profile_dict

    decision = run_follow_up_agent(session, public_id, profile)

    if decision.action == "send_message":
        logger.info("[%s] follow_up drafted message for %s (awaiting approval)", session.campaign, public_id)
        
        from chat.models import ChatMessage
        from django.contrib.contenttypes.models import ContentType
        from crm.models import Lead
        from crm.models.deal import Deal
        import uuid
        
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        if deal:
            # Dedup guard: check for existing pending draft
            has_draft = ChatMessage.objects.filter(
                content_type=ContentType.objects.get_for_model(Lead),
                object_id=deal.lead.pk,
                is_draft=True
            ).exists()
            
            if not has_draft:
                # Standardize on Lead as the target object
                ChatMessage.objects.create(
                    content_type=ContentType.objects.get_for_model(Lead),
                    object_id=deal.lead.pk,
                    campaign=deal.campaign,
                    content=decision.message,
                    is_outgoing=True,
                    is_draft=True,
                    is_approved=False,
                    owner=session.linkedin_profile.user,
                    linkedin_urn=f"draft_{uuid.uuid4()}"
                )
                logger.info("Draft saved safely to Dashboard. Admin approval required.")
            else:
                logger.info("A draft message already exists for %s — skipping creation.", public_id)

    elif decision.action == "mark_completed":
        set_profile_state(session, public_id, ProfileState.COMPLETED.value, reason=decision.reason)

    elif decision.action == "wait":
        from crm.models.deal import Deal
        deal = Deal.objects.filter(lead__public_identifier=public_id, campaign=session.campaign).first()
        enqueue_follow_up(campaign_id, public_id, delay_seconds=decision.follow_up_hours * 3600, deal=deal)
