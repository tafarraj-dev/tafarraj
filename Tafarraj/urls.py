from django.urls import path
from . import views
from .views import auto_find_links

app_name = 'tafarraj'

urlpatterns = [
    path('', views.drama_list, name='drama_list'),
    path('drama/<int:pk>/', views.drama_detail, name='drama_detail'),
    path('link-tool/', views.link_tool, name='link_tool'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('my-list/', views.my_list_view, name='my_list'),
    path('api/save-drama/', views.save_drama_api, name='save_drama_api'),
    path('api/top-dramas/', views.top_dramas_api, name='top_dramas_api'),
    path('api/save-watch-link/', views.save_watch_link_api, name='save_watch_link_api'),
    path('api/auto-find-links/', auto_find_links),
    path('api/watch-click/', views.record_watch_click, name='record_watch_click'),
    path('autocomplete/', views.drama_autocomplete, name='autocomplete'),
]