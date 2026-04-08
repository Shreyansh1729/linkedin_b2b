from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from linkedin.models import Campaign, LinkedInProfile, Task, ActionLog
from crm.models.lead import Lead

def dashboard_callback(request, context):
    """
    Enhanced LeadPilot Dashboard Callback.
    Returns structured data for the Unfold Dashboard.
    """
    total_leads = Lead.objects.count()
    active_campaigns = Campaign.objects.count()
    pending_tasks = Task.objects.filter(status="pending").count()
    
    try:
        latest_action = ActionLog.objects.latest('created_at')
        actions_today = ActionLog.objects.filter(created_at__date=latest_action.created_at.date()).count()
    except ActionLog.DoesNotExist:
        actions_today = 0
        
    active_profile = LinkedInProfile.objects.filter(active=True).first()

    # Unfold indicators for a "WOW" developer dashboard
    context.update({
        "greeting": "LeadPilot Console",
        "tagline": "Autonomous B2B Lead Generation Active",
        "kpi": [
            {
                "title": "Total Leads Found",
                "metric": str(total_leads),
                "icon": "users",
                "color": "success",
            },
            {
                "title": "Active Campaigns",
                "metric": str(active_campaigns),
                "icon": "send",
                "color": "info",
            },
            {
                "title": "Pending Tasks",
                "metric": str(pending_tasks),
                "icon": "list_checks",
                "color": "warning" if pending_tasks > 0 else "success",
            },
            {
                "title": "Actions Today",
                "metric": str(actions_today),
                "icon": "activity",
                "color": "primary",
            },
        ],
        "profile_status": "🟢 CONNECTED" if (active_profile and active_profile.cookie_data) else "🔴 DISCONNECTED",
    })
    return context
