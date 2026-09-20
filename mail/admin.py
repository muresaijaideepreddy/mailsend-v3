from django.contrib import admin

from .models import Attachment, AuditEvent, GoogleCredential, Membership, Message, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "executive")
    search_fields = ("name", "executive__username")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "workspace", "role")
    list_filter = ("role",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "workspace", "created_by", "send_date", "status")
    list_filter = ("status", "workspace")
    search_fields = ("subject", "to")
    readonly_fields = ("workspace", "created_by", "to", "cc", "bcc", "subject", "body", "send_date", "status", "version", "provider_id", "sent_at", "sent_signature", "last_error", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "workspace", "actor", "created_at")
    readonly_fields = ("workspace", "actor", "message", "action", "detail", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# OAuth token ciphertext and raw attachment paths are deliberately not exposed
# in the admin. Use the application to connect Google or download attachments.
