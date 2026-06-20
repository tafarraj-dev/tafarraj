from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


# ─── CUSTOM USER MANAGER ───────────────────────────────────────────────────────

class CustomUserManager(BaseUserManager):

    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        if not username:
            raise ValueError('Username is required')
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, username, password, **extra_fields)


# ─── CUSTOM USER ───────────────────────────────────────────────────────────────

class CustomUser(AbstractBaseUser, PermissionsMixin):
    email      = models.EmailField(unique=True)
    username   = models.CharField(max_length=50, unique=True)
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    groups = models.ManyToManyField(
        'auth.Group',
        blank=True,
        related_name='tafarraj_users',
        related_query_name='tafarraj_user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        blank=True,
        related_name='tafarraj_users',
        related_query_name='tafarraj_user',
    )

    objects = CustomUserManager()

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.username


# ─── WATCH SITE ────────────────────────────────────────────────────────────────

class WatchSite(models.Model):
    name     = models.CharField(max_length=100)
    domain   = models.CharField(max_length=100, unique=True)
    logo_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.name


# ─── USER PROFILE ──────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    user            = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    preferred_sites = models.ManyToManyField(WatchSite, blank=True)

    def __str__(self):
        return f"Profile — {self.user.username}"


# ─── GENRE ─────────────────────────────────────────────────────────────────────

class Genre(models.Model):
    name        = models.CharField(max_length=50)
    name_arabic = models.CharField(max_length=50)

    def __str__(self):
        return self.name_arabic or self.name


# ─── DRAMA ─────────────────────────────────────────────────────────────────────

class Drama(models.Model):

    COUNTRY_CHOICES = [
        ('korean',   'كوري'),
        ('turkish',  'تركي'),
        ('japanese', 'ياباني'),
        ('chinese',  'صيني'),
        ('moroccan', 'مغربي'),
        ('thai',     'تايلندي'),
    ]

    STATUS_CHOICES = [
        ('ongoing',   'مستمر'),
        ('completed', 'مكتمل'),
    ]

    # Basic info
    title          = models.CharField(max_length=200)
    title_arabic   = models.CharField(max_length=200, blank=True)
    title_original = models.CharField(max_length=200, blank=True)

    # Visual
    thumbnail     = models.ImageField(upload_to='thumbnails/', blank=True, null=True)
    thumbnail_url = models.URLField(blank=True, null=True)

    # Details
    description        = models.TextField()
    description_arabic = models.TextField(blank=True)
    country            = models.CharField(max_length=50, choices=COUNTRY_CHOICES)

    # Episodes
    total_episodes         = models.IntegerField()
    episode_duration       = models.IntegerField()
    release_year           = models.IntegerField()
    status                 = models.CharField(max_length=20, choices=STATUS_CHOICES)
    next_episode_date      = models.DateTimeField(blank=True, null=True)
    current_episode_number = models.IntegerField(default=0)
    tmdb_id                = models.IntegerField(null=True, blank=True, unique=True)

    # Categories
    genres = models.ManyToManyField(Genre)

    def __str__(self):
        return self.title_arabic or self.title


# ─── WATCH LINK ────────────────────────────────────────────────────────────────

class WatchLink(models.Model):

    ADS_CHOICES = [
        ('none',     'بدون إعلانات'),
        ('few',      'إعلانات قليلة'),
        ('moderate', 'إعلانات متوسطة'),
        ('heavy',    'إعلانات كثيرة'),
    ]

    COMPLETENESS_CHOICES = [
        ('complete',     'مكتملة'),
        ('missing_some', 'تنقصها بعض الحلقات'),
        ('incomplete',   'غير مكتملة'),
    ]

    drama                = models.ForeignKey(Drama, on_delete=models.CASCADE, related_name='links')
    website_name         = models.CharField(max_length=100)
    url                  = models.URLField()
    language             = models.CharField(max_length=20, choices=[
                               ('arabic',  'Arabic Subs'),
                               ('english', 'English Subs'),
                           ])
    episodes_available   = models.IntegerField()
    is_free              = models.BooleanField(default=True)
    has_arabic_subtitles = models.BooleanField(default=True)
    ads_level            = models.CharField(max_length=20, choices=ADS_CHOICES, default='moderate')
    episodes_completeness= models.CharField(max_length=20, choices=COMPLETENESS_CHOICES, default='complete')

    def __str__(self):
        return f"{self.website_name} — {self.drama.title}"


# ─── SAVED DRAMA ───────────────────────────────────────────────────────────────

class SavedDrama(models.Model):

    LIST_CHOICES = [
        ('watchlist',  'قائمة المشاهدة'),
        ('favorites',  'المفضلة'),
        ('completed',  'شاهدته'),
    ]

    user       = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='saved_dramas')
    drama      = models.ForeignKey(Drama, on_delete=models.CASCADE, related_name='saved_by')
    list_type  = models.CharField(max_length=20, choices=LIST_CHOICES, default='watchlist')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'drama', 'list_type')

    def __str__(self):
        return f"{self.user.username} → {self.drama.title_arabic} [{self.list_type}]"


# ─── WATCH HISTORY ─────────────────────────────────────────────────────────────

class WatchHistory(models.Model):
    user                 = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='watch_history')
    drama                = models.ForeignKey(Drama, on_delete=models.CASCADE, related_name='watched_by')
    last_episode_watched = models.IntegerField(default=0)
    last_watched_site    = models.ForeignKey(WatchSite, on_delete=models.SET_NULL, null=True, blank=True)
    last_updated         = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'drama')

    def __str__(self):
        return f"{self.user.username} watched {self.drama.title_arabic} up to ep {self.last_episode_watched}"