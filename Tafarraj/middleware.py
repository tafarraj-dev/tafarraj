from django.core.cache import cache
from django.http import HttpResponseForbidden

def is_banned(ip):
    return cache.get(f"banned:{ip}", False)

def track_and_ban(ip, limit=60, window=60, ban_seconds=3600):
    key = f"reqcount:{ip}"
    count = cache.get(key, 0)
    if count == 0:
        cache.set(key, 1, timeout=window)
    else:
        cache.incr(key)
    if count + 1 > limit:
        cache.set(f"banned:{ip}", True, timeout=ban_seconds)

class BlockBannedIPsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = request.META.get('REMOTE_ADDR')
        if is_banned(ip):
            return HttpResponseForbidden("Access denied.")
        track_and_ban(ip)
        return self.get_response(request)