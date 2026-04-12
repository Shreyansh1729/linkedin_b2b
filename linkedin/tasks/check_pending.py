# linkedin/tasks/check_pending.py
"""Check pending task — checks one PENDING profile, self-reschedules with backoff."""
from __future__ import annotations

import logging

from termcolor import colored

from django.db import transaction

from linkedin.db.deals import deal_to_profile_dict, set_profile_state
from linkedin.enums import ProfileState
from linkedin.exceptions import SkipProfile

logger = logging.getLogger(__name__)


def handle_check_pending(task, session, qualifiers):
    from crm.models import Deal
    from linkedin.actions.status import get_connection_status
    from linkedin.tasks.connect import enqueue_check_pending, enqueue_follow_up

    payload = task.payload
    public_id = payload.get("public_id")
    if not public_id:
        logger.error("check_pending: missing public_id in task %s", task.pk)
        return

    campaign_id = payload["campaign_id"]
    backoff_hours = payload.get("backoff_hours", 24)

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 check_pending", "magenta", attrs=["bold"]), public_id,
    )

    deal = Deal.objects.filter(
        lead__public_identifier=public_id, 
        campaign=session.campaign
    ).select_related("lead").first()

    if deal is None:
        raise RuntimeError(f"check_pending: no Deal found for {public_id}")

    profile_dict = deal_to_profile_dict(deal)
    profile = profile_dict.get("profile") or profile_dict
    
    # Age limit: auto-fail if PENDING for > 30 days
    from datetime import timedelta
    from django.utils import timezone
    if deal.creation_date < timezone.now() - timedelta(days=30):
        logger.info("[%s] Deal for %s expired (> 30 days PENDING) — marking FAILED", session.campaign, public_id)
        set_profile_state(session, public_id, ProfileState.FAILED.value, reason="Expired: PENDING for > 30 days")
        return

    try:
        new_state = get_connection_status(session, profile)
    except SkipProfile as e:
        logger.warning("Skipping %s: %s", public_id, e)
        set_profile_state(session, public_id, ProfileState.FAILED.value)
        return

    set_profile_state(session, public_id, new_state.value)

    if new_state == ProfileState.CONNECTED:
        enqueue_follow_up(campaign_id, public_id, deal=deal)
    elif new_state == ProfileState.PENDING:
        new_backoff = min(backoff_hours * 2, 168)
        with transaction.atomic():
            if deal:
                deal.backoff_hours = new_backoff
                deal.save(update_fields=["backoff_hours"])
        delay_hours = enqueue_check_pending(campaign_id, public_id, backoff_hours=new_backoff, deal=deal)
        logger.info(
            "%s still pending — scheduled in %.1fh (backoff %.1fh → %.1fh)",
            public_id, delay_hours, backoff_hours, new_backoff,
        )
