# linkedin/tasks/check_pending.py
"""Check pending task — checks one PENDING profile, self-reschedules with backoff."""
from __future__ import annotations

import logging

from termcolor import colored

from django.db import transaction

from linkedin.db.deals import get_profile_dict_for_public_id, set_profile_state
from linkedin.enums import ProfileState
from linkedin.exceptions import SkipProfile

logger = logging.getLogger(__name__)


def handle_check_pending(task, session, qualifiers):
    from crm.models import Deal
    from linkedin.actions.status import get_connection_status
    from linkedin.tasks.connect import enqueue_check_pending, enqueue_follow_up

    payload = task.payload
    public_id = payload["public_id"]
    campaign_id = payload["campaign_id"]
    backoff_hours = payload.get("backoff_hours", 24)

    logger.info(
        "[%s] %s %s",
        session.campaign, colored("\u25b6 check_pending", "magenta", attrs=["bold"]), public_id,
    )

    profile_dict = get_profile_dict_for_public_id(session, public_id)
    if profile_dict is None:
        logger.warning("check_pending: no Deal for %s — skipping", public_id)
        return

    profile = profile_dict.get("profile") or profile_dict

    try:
        new_state = get_connection_status(session, profile)
    except SkipProfile as e:
        logger.warning("Skipping %s: %s", public_id, e)
        set_profile_state(session, public_id, ProfileState.FAILED.value)
        return

    set_profile_state(session, public_id, new_state.value)

    if new_state == ProfileState.CONNECTED:
        enqueue_follow_up(campaign_id, public_id)
    elif new_state == ProfileState.PENDING:
        new_backoff = backoff_hours * 2
        with transaction.atomic():
            deal = Deal.objects.filter(
                lead__public_identifier=public_id,
                campaign=session.campaign,
            ).first()
            if deal:
                deal.backoff_hours = new_backoff
                deal.save(update_fields=["backoff_hours"])
        delay_hours = enqueue_check_pending(campaign_id, public_id, backoff_hours=new_backoff)
        logger.info(
            "%s still pending — scheduled in %.1fh (backoff %.1fh → %.1fh)",
            public_id, delay_hours, backoff_hours, new_backoff,
        )
