from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    CustomUser, UserProfile, WatchSite,
    Drama, Genre, WatchLink,
    SavedDrama, WatchHistory
)


# ─── CUSTOM USER ───────────────────────────────────────────────────────────────

@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    model = CustomUser
    list_display  = ('username', 'email', 'is_staff', 'is_active', 'created_at')
    list_filter   = ('is_staff', 'is_active')
    search_fields = ('username', 'email')
    ordering      = ('-created_at',)

    fieldsets = (
        (None,           {'fields': ('email', 'username', 'password')}),
        ('Permissions',  {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields':  ('email', 'username', 'password1', 'password2', 'is_staff', 'is_active'),
        }),
    )


# ─── USER PROFILE ──────────────────────────────────────────────────────────────

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ('user',)
    search_fields = ('user__username', 'user__email')
    filter_horizontal = ('preferred_sites',)


# ─── WATCH SITE ────────────────────────────────────────────────────────────────

@admin.register(WatchSite)
class WatchSiteAdmin(admin.ModelAdmin):
    list_display  = ('name', 'domain')
    search_fields = ('name', 'domain')


# ─── GENRE ─────────────────────────────────────────────────────────────────────

@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display  = ('name', 'name_arabic')
    search_fields = ('name', 'name_arabic')


# ─── DRAMA ─────────────────────────────────────────────────────────────────────

@admin.register(Drama)
class DramaAdmin(admin.ModelAdmin):
    list_display  = ('title_arabic', 'title', 'country', 'release_year', 'status')
    list_filter   = ('country', 'status', 'release_year')
    search_fields = ('title', 'title_arabic', 'title_original')
    filter_horizontal = ('genres',)


# ─── WATCH LINK ────────────────────────────────────────────────────────────────

@admin.register(WatchLink)
class WatchLinkAdmin(admin.ModelAdmin):
    list_display  = ('drama', 'website_name', 'is_free', 'has_arabic_subtitles', 'ads_level')
    list_filter   = ('website_name', 'is_free', 'has_arabic_subtitles', 'ads_level')
    search_fields = ('drama__title_arabic', 'website_name')


# ─── SAVED DRAMA ───────────────────────────────────────────────────────────────

@admin.register(SavedDrama)
class SavedDramaAdmin(admin.ModelAdmin):
    list_display  = ('user', 'drama', 'list_type', 'created_at')
    list_filter   = ('list_type',)
    search_fields = ('user__username', 'drama__title_arabic')


# ─── WATCH HISTORY ─────────────────────────────────────────────────────────────

@admin.register(WatchHistory)
class WatchHistoryAdmin(admin.ModelAdmin):
    list_display  = ('user', 'drama', 'last_episode_watched', 'last_watched_site', 'last_updated')
    search_fields = ('user__username', 'drama__title_arabic')