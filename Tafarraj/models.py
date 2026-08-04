from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils.text import slugify


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
    name        = models.CharField(max_length=50, unique=True)
    name_arabic = models.CharField(max_length=50, blank=True)
    slug        = models.SlugField(max_length=60, unique=True, blank=True, null=True, allow_unicode=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name_arabic or self.name

class Tag(models.Model):
    name        = models.CharField(max_length=100, unique=True)
    name_arabic = models.CharField(max_length=100, blank=True)
    slug        = models.SlugField(max_length=110, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name, allow_unicode=True)
            slug = base_slug
            counter = 1
            while Tag.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f"{base_slug}-{counter}"
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

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
    thumbnail          = models.ImageField(upload_to='thumbnails/', blank=True, null=True)
    thumbnail_url      = models.URLField(blank=True, null=True)
    thumbnail_position = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Leave blank for default (top). Or try: center, bottom, top, or '50% 20%'"
    )

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
    mdl_rating = models.FloatField(null=True, blank=True)
    quality_score = models.FloatField(null=True, blank=True, default=0)
    mdl_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    aired_start_date = models.DateField(null=True, blank=True)
    aired_end_date   = models.DateField(null=True, blank=True)
    content_rating   = models.CharField(max_length=100, blank=True)
    mdl_rank         = models.IntegerField(null=True, blank=True)
    mdl_popularity   = models.IntegerField(null=True, blank=True)
    last_mdl_refresh = models.DateTimeField(null=True, blank=True)
    homepage_url = models.URLField(blank=True, default="", max_length=500)
    aradrama_checked = models.BooleanField(default=False)

    # --- TMDB-sourced metrics (kept separate from MDL fields on purpose) ---
    tmdb_rating = models.FloatField(null=True, blank=True)        # TMDB vote_average, 0-10
    tmdb_vote_count = models.IntegerField(null=True, blank=True)  # TMDB vote_count
    tmdb_popularity = models.FloatField(null=True, blank=True)    # TMDB popularity score

    # Categories
    genres = models.ManyToManyField(Genre)
    tags   = models.ManyToManyField(Tag, blank=True)

    homepage_url = models.URLField(blank=True, default="", max_length=500)

    def __str__(self):
        return self.title_arabic or self.title
    
class AlternateTitle(models.Model):
    drama = models.ForeignKey(Drama, on_delete=models.CASCADE, related_name='alternate_titles')
    title = models.CharField(max_length=200)

    class Meta:
        unique_together = ('drama', 'title')

    def __str__(self):
        return f"{self.title} ({self.drama.title})"


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