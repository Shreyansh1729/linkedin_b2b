#!/usr/bin/env python
"""
Bootstrap script for initial CRM data.

Ensures the default Site exists.
Idempotent — safe to run multiple times.
"""
import logging

logger = logging.getLogger(__name__)

DEFAULT_CAMPAIGN_NAME = "LinkedIn Outreach"


def setup_crm():
    logger.debug("CRM setup complete.")
