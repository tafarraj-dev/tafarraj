from django.contrib.sitemaps import Sitemap
from .models import Drama

class DramaSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Drama.objects.all()

    def location(self, obj):
        return f'/drama/{obj.pk}/'