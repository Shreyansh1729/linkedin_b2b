# LeadPilot: B2B LinkedIn Automation

LeadPilot is a proprietary, closed-source B2B automated outreach platform. It acts as an autonomous sales agent that discovers, qualifies, and messages high-value prospects without requiring pre-built contact lists.

## System Architecture

LeadPilot operates entirely locally through a robust three-tier architecture:

1. **The Intelligence Engine**: Built on local Gaussian Process Regression and the Gemini 3.1 LLM, this engine scores profiles in real-time, learning from prior decisions.
2. **The Automation Daemon**: A headless Playwright worker that mimics human typing patterns to bypass LinkedIn security limits.
3. **The CRM Dashboard**: A premium, Unfold-powered Django admin panel where sales operators can track leads, visualize the pipeline, and approve AI-drafted messages in a Human-In-The-Loop flow.

---

## 🚀 Quick Setup Guide

### 1. Installation
Ensure you have Python 3.12+ and Git installed on your server or local machine.

```bash
# Clone the repository
git clone <your-private-repo-url>
cd LeadPilot

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install -r requirements/local.txt

# Install Playwright browser dependencies
playwright install --with-deps chromium

# Initialize the database and run migrations
python manage.py migrate

# Seed initial CRM settings
python manage.py setup_crm
```

### 2. Administrator Access
To manage the platform, create a dashboard superuser account:

```bash
python manage.py createsuperuser
```

### 3. Launching

You need to run two parallel processes: The CRM Dashboard and the Automation Engine.

**Terminal 1: Start the Dashboard**
```bash
make admin
# Open http://localhost:8000/admin in your browser
```

**Terminal 2: Start the Engine**
```bash
make run
```
On first launch, the CLI wizard will prompt you to securely inject your `GEMINI_API_KEY` and LinkedIn account credentials natively into the PostgreSQL / SQLite vault.

---

## The HitL (Human-In-The-Loop) Workflow
This proprietary branch of LeadPilot emphasizes safety in executive outreach. 

1. **Discovery**: AI autonomously navigates and adds profiles to the `Leads` table.
2. **Connection**: AI ranks leads and natively dispatches connection requests, creating a `Deal`.
3. **Drafting (HitL)**: When a connection connects, the Gemini model drafts a highly personalized introductory message. It marks this as a **Draft**.
4. **Approval**: From the Admin Dashboard -> Messages, staff must review, edit, and click **[Approve & Send]**. The Playwright daemon picks up the approved draft and dispatches it cleanly.

---
*Confidential and Proprietary. Do not distribute outside of authorized company personnel.*
