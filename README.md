# LeadPilot: B2B LinkedIn Outreach System

LeadPilot is a system for automated LinkedIn outreach, integrating lead discovery, qualification, and messaging into a unified CRM pipeline.

## System Components

1.  **Lead Scoring Pipeline**: Uses Gaussian Process Regression and Large Language Model (LLM) integration to qualify leads based on profile data and campaign objectives.
2.  **Automation Engine**: A Playwright-based background worker that executes LinkedIn actions (profile visits, connection requests, messaging) at scheduled intervals.
3.  **CRM Dashboard**: An Unfold-powered Django administration interface for managing campaigns, monitoring lead states, and approving message drafts.

## Setup Instructions

### 1. Installation
Requires Python 3.10+ and Playwright.

```bash
# Setup virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements/local.txt
playwright install chromium
```

### 2. Initialization
```bash
# Database setup
python manage.py migrate
python manage.py setup_crm

# Create administration user
python manage.py createsuperuser
```

### 3. Execution
The system requires two processes to run concurrently:

**Dashboard (UI):**
```bash
python manage.py runserver
```

**Automation Daemon (Worker):**
```bash
python manage.py rundaemon
```

## Security and Configuration

- **Encryption**: Sensitive credentials (LinkedIn passwords, API keys) are encrypted using Fernet (AES). The `LEADPILOT_ENCRYPTION_KEY` environment variable must be set in production.
- **Rate Limits**: Connection and follow-up limits are configured per LinkedIn profile via the administration dashboard.
- **Active Hours**: The system respects `ACTIVE_START_HOUR` and `ACTIVE_END_HOUR` settings to mimic human operating windows.

## Operational Workflow (HitL)

1.  **Lead Discovery**: System identifies potential prospects and adds them to the database.
2.  **Qualification**: Lead profiles are scored and transitioned to the `QUALIFIED` state if they match campaign criteria.
3.  **Connection**: System dispatches connection requests. Once accepted, the deal transitions to `CONNECTED`.
4.  **Messaging (Human-In-The-Loop)**: System generates a personalized message draft.
5.  **Approval**: Operators review drafts in the dashboard and trigger dispatch.
