# linkedin/daemon.py
from __future__ import annotations

import logging
import random
import time
import traceback
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from termcolor import colored

from linkedin.exceptions import TaskSkipped

from linkedin.conf import (
    ACTIVE_END_HOUR,
    ACTIVE_START_HOUR,
    ACTIVE_TIMEZONE,
    CAMPAIGN_CONFIG,
    ENABLE_ACTIVE_HOURS,
    REST_DAYS,
)
from linkedin.diagnostics import failure_diagnostics
from linkedin.ml.qualifier import BayesianQualifier, KitQualifier
from linkedin.models import Task
from linkedin.tasks.check_pending import handle_check_pending
from linkedin.tasks.connect import enqueue_check_pending, enqueue_connect, enqueue_follow_up, handle_connect
from linkedin.tasks.follow_up import handle_follow_up
from linkedin.tasks.send_message import handle_send_message

logger = logging.getLogger(__name__)


_HANDLERS = {
    Task.TaskType.CONNECT: handle_connect,
    Task.TaskType.CHECK_PENDING: handle_check_pending,
    Task.TaskType.FOLLOW_UP: handle_follow_up,
    Task.TaskType.SEND_MESSAGE: handle_send_message,
}





def _build_qualifiers(campaigns, cfg):
    """Create a qualifier for every campaign, keyed by campaign PK."""
    from crm.models import Lead

    qualifiers: dict[int, BayesianQualifier | KitQualifier] = {}
    n_regular = 0
    for campaign in campaigns:
        if campaign.is_freemium:
            km = campaign.load_ml_model()
            if km:
                qualifiers[campaign.pk] = KitQualifier(km)
                logger.info(colored("Kit model loaded", "cyan") + " for freemium campaign %s", campaign)
            continue
        
        q = BayesianQualifier(
            seed=42,
            n_mc_samples=cfg["qualification_n_mc_samples"],
            campaign=campaign,
        )
        X, y = Lead.get_labeled_arrays(campaign)
        if len(X) > 0:
            q.warm_start(X, y)
            logger.info(
                colored("GP qualifier warm-started", "cyan")
                + " on %d labelled samples (%d positive, %d negative)"
                + " for campaign %s",
                len(y), int((y == 1).sum()), int((y == 0).sum()), campaign,
            )
        qualifiers[campaign.pk] = q
        n_regular += 1

    return qualifiers


# ------------------------------------------------------------------
# Schedule guard
# ------------------------------------------------------------------


def seconds_until_active() -> float:
    """Return seconds to wait before the next active window, or 0 if active now."""
    if not ENABLE_ACTIVE_HOURS:
        return 0.0
    tz = ZoneInfo(ACTIVE_TIMEZONE)
    now = timezone.localtime(timezone=tz)

    if now.weekday() not in REST_DAYS and ACTIVE_START_HOUR <= now.hour < ACTIVE_END_HOUR:
        return 0.0

    # Find the next active start: try today first, then subsequent days
    candidate = timezone.make_aware(
        now.replace(hour=ACTIVE_START_HOUR, minute=0, second=0, microsecond=0, tzinfo=None),
        timezone=tz,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() in REST_DAYS:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()


# ------------------------------------------------------------------
# Task queue worker
# ------------------------------------------------------------------


def heal_tasks(session):
    """Reconcile task queue with CRM state on daemon startup.

    1. Reset stale 'running' tasks to 'pending' (crashed worker recovery)
    2. Seed one 'connect' task per campaign if none pending
    3. Create 'check_pending' tasks for PENDING profiles without tasks
    4. Create 'follow_up' tasks for CONNECTED profiles without tasks
    """
    from crm.models import Deal
    from linkedin.enums import ProfileState

    cfg = CAMPAIGN_CONFIG

    # 1. Recover stale running tasks
    stale_count = Task.objects.filter(status=Task.Status.RUNNING).update(
        status=Task.Status.PENDING,
    )
    if stale_count:
        logger.info("Recovered %d stale running tasks", stale_count)

    # 2. Seed connect tasks per campaign (regular first, freemium deferred)
    for campaign in session.campaigns:
        delay = CAMPAIGN_CONFIG["connect_delay_seconds"] if campaign.is_freemium else 0
        enqueue_connect(campaign.pk, delay_seconds=delay)

    # 3. Check_pending tasks for PENDING profiles
    for campaign in session.campaigns:
        session.campaign = campaign
        pending_deals = Deal.objects.filter(
            state=ProfileState.PENDING,
            campaign=campaign,
        ).select_related("lead")

        for deal in pending_deals:
            public_id = deal.lead.public_identifier
            if not public_id:
                continue
            backoff = deal.backoff_hours or cfg["check_pending_recheck_after_hours"]
            enqueue_check_pending(campaign.pk, public_id, backoff_hours=backoff, deal=deal)

    # 4. Follow_up tasks for CONNECTED profiles
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType

    for campaign in session.campaigns:
        session.campaign = campaign
        connected_deals = Deal.objects.filter(
            state=ProfileState.CONNECTED,
            campaign=campaign,
        ).select_related("lead")

        for deal in connected_deals:
            public_id = deal.lead.public_identifier
            if not public_id:
                continue
            
            # Check for existing pending draft OR pending SEND_MESSAGE task
            has_pending_draft = ChatMessage.objects.filter(
                content_type=ContentType.objects.get_for_model(deal.lead),
                object_id=deal.lead.pk, 
                is_draft=True
            ).exists()
            
            has_send_task = Task.objects.filter(
                task_type=Task.TaskType.SEND_MESSAGE,
                status__in=[Task.Status.PENDING, Task.Status.RUNNING],
                payload__public_id=public_id
            ).exists()

            if has_pending_draft or has_send_task:
                continue

            enqueue_follow_up(campaign.pk, public_id, delay_seconds=random.uniform(5, 60), deal=deal)


    pending_count = Task.objects.pending().count()
    logger.info("Task queue healed: %d pending tasks", pending_count)


def run_daemon(session):
    from linkedin.models import Campaign

    cfg = CAMPAIGN_CONFIG

    qualifiers = _build_qualifiers(session.campaigns, cfg)

    # Startup healing
    heal_tasks(session)

    campaigns = session.campaigns
    if not campaigns:
        logger.error("No campaigns found — cannot start daemon")
        return

    logger.info(
        colored("Daemon started", "green", attrs=["bold"])
        + " — %d campaigns, task queue worker",
        len(campaigns),
    )



    # Single-threaded: one task at a time, no concurrent enqueuing,
    # so sleeping until the next scheduled_at is safe.
    while True:
        pause = seconds_until_active()
        if pause > 0:
            h, m = int(pause // 3600), int(pause % 3600 // 60)
            logger.info("Outside active hours — sleeping %dh%02dm", h, m)
            time.sleep(pause)
            continue

        task = Task.objects.claim_next()
        if task is None:
            wait = Task.objects.seconds_to_next()
            if wait is None:
                logger.info("Queue empty — nothing to do")
                return
            if wait > 0:
                h, m = int(wait // 3600), int(wait % 3600 // 60)
                logger.info("Next task in %dh%02dm — sleeping", h, m)
                time.sleep(wait)
            continue

        campaign = Campaign.objects.filter(pk=task.payload.get("campaign_id")).first()
        if not campaign:
            task.mark_failed(f"Campaign {task.payload.get('campaign_id')} not found")
            continue

        session.campaign = campaign
        task.mark_running()

        handler = _HANDLERS.get(task.task_type)
        if handler is None:
            task.mark_failed(f"Unknown task type: {task.task_type}")
            continue

        try:
            with failure_diagnostics(session):
                handler(task, session, qualifiers)
            task.mark_completed()
        except TaskSkipped as e:
            task.mark_skipped(str(e))
            logger.info("Task %s skipped: %s", task, str(e))
        except Exception:
            task.mark_failed(traceback.format_exc())
            logger.exception("Task %s failed", task)
            continue

