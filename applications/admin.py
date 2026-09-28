from django.contrib import admin

from .models import Application, StatusChange


class StatusChangeInline(admin.TabularInline):
    model = StatusChange
    extra = 0
    readonly_fields = ["from_status", "to_status", "changed_at"]
    can_delete = False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["listing", "user", "status", "applied_at", "listing_is_active", "updated_at"]
    list_filter = ["status", "listing__is_active"]
    search_fields = ["listing__company", "listing__title", "user__username", "notes"]
    list_select_related = ["listing", "user"]
    # A search box instead of a dropdown holding thousands of listings.
    raw_id_fields = ["listing"]
    inlines = [StatusChangeInline]

    @admin.display(boolean=True, description="Listing open")
    def listing_is_active(self, obj):
        return obj.listing.is_active


@admin.register(StatusChange)
class StatusChangeAdmin(admin.ModelAdmin):
    list_display = ["application", "from_status", "to_status", "changed_at"]
    list_filter = ["to_status"]
    list_select_related = ["application__listing", "application__user"]
