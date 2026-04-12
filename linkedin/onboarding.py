# linkedin/onboarding.py
"""Onboarding: create Campaign + LinkedInProfile + LLM config in DB.

Two ways to supply config:
- OnboardConfig.from_json(path) — from a JSON file (non-interactive / cloud).
- collect_from_wizard()         — interactive questionary wizard (needs TTY).

Both return an OnboardConfig; ``apply()`` is the single write path.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

from linkedin.conf import (
    DEFAULT_CONNECT_DAILY_LIMIT,
    DEFAULT_CONNECT_WEEKLY_LIMIT,
    DEFAULT_FOLLOW_UP_DAILY_LIMIT,
    ROOT_DIR,
)

DEFAULT_PRODUCT_DOCS = ROOT_DIR / "README.md"
DEFAULT_CAMPAIGN_OBJECTIVE = "B2B Lead Discovery and Automated Outreach"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config dataclass (pure data — no I/O)
# ---------------------------------------------------------------------------

@dataclass
class OnboardConfig:
    """All values needed to onboard — filled interactively or from JSON."""

    linkedin_email: str = ""
    linkedin_password: str = ""
    campaign_name: str = ""
    product_description: str = ""
    campaign_objective: str = ""
    booking_link: str = ""
    seed_urls: str = ""
    llm_api_key: str = ""
    ai_model: str = "gemini-1.5-pro"
    llm_api_base: str = ""
    newsletter: bool = True
    connect_daily_limit: int = DEFAULT_CONNECT_DAILY_LIMIT
    connect_weekly_limit: int = DEFAULT_CONNECT_WEEKLY_LIMIT
    follow_up_daily_limit: int = DEFAULT_FOLLOW_UP_DAILY_LIMIT

    @classmethod
    def from_json(cls, path: str) -> OnboardConfig:
        import json
        with open(path) as f:
            data = json.load(f)
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


# ---------------------------------------------------------------------------
# State inspection
# ---------------------------------------------------------------------------

_CAMPAIGN_KEYS = {
    "campaign_name", "product_description", "campaign_objective",
    "booking_link", "seed_urls",
}
_ACCOUNT_KEYS = {
    "linkedin_email", "linkedin_password", "newsletter",
    "connect_daily_limit", "connect_weekly_limit", "follow_up_daily_limit",
}
_LLM_KEYS = {"llm_api_key", "ai_model", "llm_api_base"}
_ALL_KEYS = _CAMPAIGN_KEYS | _ACCOUNT_KEYS | _LLM_KEYS


def missing_keys() -> set[str]:
    """Return onboarding field keys that still need values."""
    from linkedin.models import Campaign, LinkedInProfile, SiteConfig

    keys: set[str] = set()

    if not Campaign.objects.exists():
        keys |= _CAMPAIGN_KEYS

    if not LinkedInProfile.objects.filter(active=True).exists():
        keys |= _ACCOUNT_KEYS

    cfg = SiteConfig.load()
    if not cfg:
        keys |= _LLM_KEYS
    else:
        if not cfg.llm_api_key: keys.add("llm_api_key")
        if not cfg.ai_model: keys.add("ai_model")

    return keys


# ---------------------------------------------------------------------------
# Interactive collection (needs TTY)
# ---------------------------------------------------------------------------

@dataclass
class Question:
    key: str
    message: str
    default: str = ""
    is_password: bool = False
    required: bool = True


SELF_HOSTED_QUESTIONS = [
    Question("linkedin_email", "LinkedIn Email"),
    Question("linkedin_password", "LinkedIn Password", is_password=True),
    Question("campaign_name", "Campaign Name (e.g. My Outreach)"),
    Question("product_description", "Product/Service Description", default="We help companies with..."),
    Question("campaign_objective", "Campaign Objective", default="Generate high-quality leads"),
    Question("booking_link", "Booking Link (optional)", required=False),
    Question("seed_urls", "Seed LinkedIn URLs (comma separated)", required=False),
    Question("llm_api_key", "LLM API Key (Gemini/OpenAI)"),
    Question("ai_model", "Model Identifier", default="gemini-1.5-pro"),
    Question("llm_api_base", "LLM API Base URL (optional)", required=False),
    Question("connect_daily_limit", "Daily Connection Limit", default=str(DEFAULT_CONNECT_DAILY_LIMIT)),
    Question("connect_weekly_limit", "Weekly Connection Limit", default=str(DEFAULT_CONNECT_WEEKLY_LIMIT)),
    Question("follow_up_daily_limit", "Daily Follow-up Limit", default=str(DEFAULT_FOLLOW_UP_DAILY_LIMIT)),
]


def ask(questions: list[Question]) -> dict | None:
    """Simple wrapper around questionary to ask a list of questions."""
    import questionary

    answers = {}
    for q in questions:
        if q.is_password:
            val = questionary.password(q.message).ask()
        else:
            val = questionary.text(q.message, default=q.default).ask()

        if val is None:  # User cancelled
            return None
        
        if q.required and not val.strip():
            # Minimal validation: just ask again if required field is empty
            while not val.strip():
                print(f"Error: {q.message} is required.")
                if q.is_password:
                    val = questionary.password(q.message).ask()
                else:
                    val = questionary.text(q.message, default=q.default).ask()
                if val is None:
                    return None

        answers[q.key] = val
    return answers


def collect_from_wizard() -> OnboardConfig:
    """Run the questionary wizard for missing fields; return an OnboardConfig.

    Raises SystemExit if the user cancels.
    """
    skip = _ALL_KEYS - missing_keys()
    questions = [q for q in SELF_HOSTED_QUESTIONS if q.key not in skip]
    if not questions:
        return OnboardConfig()

    answers = ask(questions)
    if answers is None:
        raise SystemExit("Onboarding cancelled.")

    # Cast numeric inputs
    for key in ["connect_daily_limit", "connect_weekly_limit", "follow_up_daily_limit"]:
        if key in answers:
            try:
                answers[key] = int(answers[key])
            except ValueError:
                pass

    return OnboardConfig(**{
        k: v for k, v in answers.items()
        if k in OnboardConfig.__dataclass_fields__
    })


# ---------------------------------------------------------------------------
# Record creation (pure DB, no I/O)
# ---------------------------------------------------------------------------

def _read_default_file(val) -> str:
    from pathlib import Path
    if isinstance(val, Path):
        return val.read_text(encoding="utf-8").strip() if val.exists() else ""
    return str(val)


def _create_campaign(name: str, product_docs: str, objective: str, booking_link: str = ""):
    """Create a Campaign record and return it."""
    from linkedin.models import Campaign

    campaign = Campaign.objects.create(
        name=name,
        product_docs=product_docs,
        campaign_objective=objective,
        booking_link=booking_link,
    )
    logger.info("Created campaign: %s", name)
    print(f"Campaign '{name}' created!")
    return campaign


def _create_account(
    campaign,
    email: str,
    password: str,
    *,
    subscribe: bool = True,
    connect_daily: int = DEFAULT_CONNECT_DAILY_LIMIT,
    connect_weekly: int = DEFAULT_CONNECT_WEEKLY_LIMIT,
    follow_up_daily: int = DEFAULT_FOLLOW_UP_DAILY_LIMIT,
):
    """Create a User + LinkedInProfile record and return the profile."""
    from django.contrib.auth.models import User
    from linkedin.models import LinkedInProfile

    handle = email.split("@")[0].lower().replace(".", "_").replace("+", "_")

    user, created = User.objects.get_or_create(
        username=handle,
        defaults={"is_staff": True, "is_active": True},
    )
    if created:
        user.set_unusable_password()
        user.save()

    if campaign:
        campaign.users.add(user)

    profile = LinkedInProfile.objects.create(
        user=user,
        linkedin_username=email,
        linkedin_password=password,
        subscribe_newsletter=subscribe,
        connect_daily_limit=connect_daily,
        connect_weekly_limit=connect_weekly,
        follow_up_daily_limit=follow_up_daily,
    )

    logger.info("Created LinkedIn profile for %s (handle=%s)", email, handle)
    print(f"Account '{handle}' created!")

    from termcolor import colored
    if user.is_staff:
        print(colored(f"\nWARNING: User '{handle}' created with NO password.", "red", attrs=["bold"]))
        print(f"To log in to the Django dashboard, you MUST run:")
        print(f"  python manage.py create_admin_user {handle}\n")

    return profile


def _create_seed_leads(campaign, seed_urls: str) -> None:
    """Parse seed URL text and create QUALIFIED leads."""
    if not seed_urls or not seed_urls.strip():
        return
    from linkedin.setup.seeds import parse_seed_urls, create_seed_leads

    public_ids = parse_seed_urls(seed_urls)
    if public_ids:
        created = create_seed_leads(campaign, public_ids)
        print(f"{created} seed profile(s) added as QUALIFIED.")


# ---------------------------------------------------------------------------
# Single write path
# ---------------------------------------------------------------------------

def apply(config: OnboardConfig) -> None:
    """Commit an OnboardConfig to the local database and filesystem."""
    from linkedin.models import Campaign, LinkedInProfile, SiteConfig

    # 1. Campaign & Seeds
    campaign = None
    if config.campaign_name:
        campaign = Campaign.objects.filter(name=config.campaign_name).first()
        if campaign is None:
            product_docs = config.product_description or _read_default_file(DEFAULT_PRODUCT_DOCS)
            objective = config.campaign_objective or _read_default_file(DEFAULT_CAMPAIGN_OBJECTIVE)
            
            campaign = _create_campaign(
                name=config.campaign_name,
                product_docs=product_docs,
                objective=objective,
                booking_link=config.booking_link,
            )
            if config.seed_urls:
                _create_seed_leads(campaign, config.seed_urls)

    # 2. LinkedIn Account
    if config.linkedin_email and not LinkedInProfile.objects.filter(linkedin_username=config.linkedin_email).exists():
        _create_account(
            campaign,
            config.linkedin_email,
            config.linkedin_password,
            subscribe=config.newsletter,
            connect_daily=config.connect_daily_limit,
            connect_weekly=config.connect_weekly_limit,
            follow_up_daily=config.follow_up_daily_limit,
        )


    # 3. LLM Configuration
    cfg = SiteConfig.load()
    if config.llm_api_key:
        cfg.llm_api_key = config.llm_api_key
    if config.ai_model:
        cfg.ai_model = config.ai_model
    if config.llm_api_base:
        cfg.llm_api_base = config.llm_api_base
    cfg.save()

    logger.info("Onboarding successful — LeadPilot is ready.")
    print("\n" + "="*60)
    print("🚀 SUCCESS: Onboarding complete. LeadPilot is ready.")
    print("="*60)
    print("\n🛡️  SECURITY NOTE: Your Django user accounts have been created with")
    print("   UNUSABLE passwords for safety.")
    print("\n👉 To log in to the admin dashboard, you MUST set an admin password.")
    print(f"   Run this command now:")
    print(f"\n      python manage.py create_admin_user {config.linkedin_email}")
    print("\n" + "="*60)
