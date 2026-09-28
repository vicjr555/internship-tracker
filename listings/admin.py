from django.contrib import admin

from .models import Listing, SyncRun, SyncState


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ["company", "title", "category", "is_active", "date_posted", "first_seen_at", "closed_at"]
    list_filter = ["is_active", "category", "sponsorship"]
    search_fields = ["company", "title", "external_id"]
    date_hierarchy = "date_posted"
    readonly_fields = ["first_seen_at", "last_seen_at", "closed_at", "raw"]


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = [
        "started_at", "status", "duration", "total_in_source",
        "new_count", "updated_count", "closed_count", "reopened_count",
    ]
    list_filter = ["status"]
    search_fields = ["error_message"]

    # Sync runs are an audit log: view-only in the admin.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SyncState)
class SyncStateAdmin(admin.ModelAdmin):
    list_display = ["__str__", "etag", "locked_at"]

    def has_add_permission(self, request):
        return not SyncState.objects.exists()
