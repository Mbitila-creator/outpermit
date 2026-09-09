class ContentSecurityPolicyMiddleware:
    """Attach the configured baseline CSP to every application response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        from django.conf import settings

        policy = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        if policy:
            response.setdefault("Content-Security-Policy", policy)
        response.setdefault(
            "Permissions-Policy",
            "camera=(self), microphone=(), geolocation=()",
        )
        return response


class PrivateMediaAccessMiddleware:
    """Reject direct URL access to private uploads; authorized views stream them."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import Http404

        media_prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
        if request.path.startswith(media_prefix):
            relative_path = request.path[len(media_prefix):]
            if any(relative_path.startswith(prefix) for prefix in settings.PRIVATE_MEDIA_PREFIXES):
                raise Http404("File not found.")
        return self.get_response(request)
