from django.contrib.auth.views import LogoutView, PasswordChangeView, PasswordChangeDoneView
from django.urls import path, reverse_lazy
from . import views, oauth_views, account_views, public_views

app_name = 'mail'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('about/', public_views.about, name='about'),
    path('privacy/', public_views.privacy, name='privacy'),
    path('terms/', public_views.terms, name='terms'),
    path('accounts/login/', views.MailLoginView.as_view(), name='login'),
    path('accounts/logout/', LogoutView.as_view(), name='logout'),
    path('accounts/password/', PasswordChangeView.as_view(template_name='registration/password_change.html', success_url=reverse_lazy('mail:password_change_done')), name='password_change'),
    path('accounts/password/done/', PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
    path('accounts/google/signin/', oauth_views.google_signin, name='google_signin'),
    path('accounts/google/identity/', oauth_views.google_identity_login, name='google_identity_login'),
    path('accounts/google/login/', oauth_views.google_login, name='google_login'),
    path('accounts/google/callback/', oauth_views.google_callback, name='google_callback'),
    path('accounts/google/disconnect/', oauth_views.google_disconnect, name='google_disconnect'),
    path('messages/new/', views.compose, name='compose'),
    path('messages/<int:pk>/edit/', views.compose, name='edit'),
    path('messages/<int:pk>/', views.detail, name='detail'),
    path('messages/<int:pk>/delete/', views.delete, name='delete'),
    path('messages/<int:pk>/send/', views.send, name='send'),
    path('send-current/', views.send_current, name='send_current'),
    path('review/<str:period>/', views.review, name='review'),
    path('sent/', views.sent, name='sent'),
    path('signature/', views.signature, name='signature'),
    path('team/', views.team, name='team'),
    path('team/<int:pk>/profile/', account_views.assistant_profile, name='assistant_profile'),
    path('team/<int:pk>/password/', account_views.assistant_password, name='assistant_password'),
    path('merge/', views.merge, name='merge'),
    path('inbox/', views.inbox, name='inbox'),
    path('attachments/<int:pk>/', views.attachment, name='attachment'),
]

