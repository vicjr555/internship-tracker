from django.core.management.base import BaseCommand, CommandError

from listings.models import SyncRun
from listings.services.sync import sync_listings


class Command(BaseCommand):
    help = "Sync internship listings from the SimplifyJobs source and print a summary."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Ignore the stored ETag and always download and process the file.",
        )

    def handle(self, *args, **options):
        run = sync_listings(force=options["force"])

        if run is None:
            self.stdout.write(self.style.WARNING("Another sync is already running. Skipped."))
            return
        if run.status == SyncRun.Status.FAILED:
            # A non-zero exit code lets schedulers and CI notice the failure.
            raise CommandError(f"Sync failed: {run.error_message}")
        if run.status == SyncRun.Status.NOT_MODIFIED:
            self.stdout.write("Source not modified since the last sync (HTTP 304). Nothing to do.")
            return

        self.stdout.write(self.style.SUCCESS(f"Sync finished in {run.duration.total_seconds():.1f}s"))
        self.stdout.write(f"  In source: {run.total_in_source}")
        self.stdout.write(f"  New:       {run.new_count}")
        self.stdout.write(f"  Updated:   {run.updated_count}")
        self.stdout.write(f"  Closed:    {run.closed_count}")
        self.stdout.write(f"  Reopened:  {run.reopened_count}")
