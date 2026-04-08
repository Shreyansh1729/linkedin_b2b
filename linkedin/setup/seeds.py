# linkedin/setup/seeds.py
"""User-provided seed profiles: parse URLs, create Leads + QUALIFIED Deals."""
from __future__ import annotations

import logging

from linkedin.url_utils import public_id_to_url, url_to_public_id
from linkedin.enums import ProfileState

logger = logging.getLogger(__name__)


def parse_seed_csv(file_bytes: bytes) -> tuple[list[str], list[str]]:
    """Parse CSV bytes to extract LinkedIn public IDs from any column.

    Handles UTF-8 with BOM (Excel) and returns (public_ids, skipped_rows).
    """
    import csv
    from io import StringIO

    text = file_bytes.decode('utf-8-sig')
    reader = csv.reader(StringIO(text))
    
    public_ids: set[str] = set()
    skipped_rows: list[str] = []
    
    for row in reader:
        found_in_row = False
        for cell in row:
            cell = cell.strip()
            if not cell:
                continue
            
            public_id = url_to_public_id(cell)
            if public_id:
                public_ids.add(public_id)
                found_in_row = True
                break
        
        if not found_in_row and any(c.strip() for c in row):
            skipped_rows.append(",".join(row))
            
    return list(public_ids), skipped_rows


def create_seed_leads(campaign, public_ids: list[str]) -> int:
    """Create url-only Leads + QUALIFIED Deals for seed profiles.

    Works without a browser session — leads will be lazily enriched
    and embedded when the daemon processes them.

    Returns the number of new seeds created.
    """
    from crm.models import Deal, Lead

    existing_seeds = set(campaign.seed_public_ids or [])
    created = 0
    for public_id in public_ids:
        url = public_id_to_url(public_id)

        lead, _ = Lead.objects.get_or_create(public_identifier=public_id, defaults={"linkedin_url": url})

        if Deal.objects.filter(lead=lead, campaign=campaign).exists():
            logger.debug("Seed %s already has a deal, skipping", public_id)
            existing_seeds.add(public_id)
            continue

        Deal.objects.create(
            lead=lead,
            campaign=campaign,
            state=ProfileState.QUALIFIED,
        )
        existing_seeds.add(public_id)
        created += 1
        logger.info("Seed %s → QUALIFIED", public_id)

    campaign.seed_public_ids = list(existing_seeds)
    campaign.save(update_fields=["seed_public_ids"])
    return created
