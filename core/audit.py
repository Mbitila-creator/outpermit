from audit.models import AuditLog


def get_client_ip(request):
    if not request:
        return None

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def get_browser_device(user_agent):
    user_agent = user_agent or ""

    if "Chrome" in user_agent and "Edg" not in user_agent:
        browser = "Chrome"
    elif "Safari" in user_agent and "Chrome" not in user_agent:
        browser = "Safari"
    elif "Firefox" in user_agent:
        browser = "Firefox"
    elif "Edg" in user_agent:
        browser = "Edge"
    else:
        browser = "Unknown Browser"

    if "Mac OS X" in user_agent:
        device = "macOS"
    elif "Windows" in user_agent:
        device = "Windows"
    elif "Android" in user_agent:
        device = "Android"
    elif "iPhone" in user_agent:
        device = "iPhone"
    elif "iPad" in user_agent:
        device = "iPad"
    elif "Linux" in user_agent:
        device = "Linux"
    else:
        device = "Unknown Device"

    return f"{browser} on {device}"


def log_action(
    user=None,
    action="SYSTEM",
    module="SYSTEM",
    reference_no=None,
    description="",
    request=None,
):
    ip_address = get_client_ip(request)
    user_agent = ""
    browser = ""
    request_url = ""
    http_method = ""

    if request:
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        browser = get_browser_device(user_agent)
        request_url = request.path
        http_method = request.method

    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        module=module,
        reference_no=reference_no,
        description=description,
        ip_address=ip_address,
        user_agent=user_agent,
        browser=browser,
        request_url=request_url,
        http_method=http_method,
    )