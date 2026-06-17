import datetime
import unittest

import api


class JobStalenessTest(unittest.TestCase):
    def test_running_job_without_recent_update_is_stale(self):
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=api.STALE_JOB_MINUTES + 1
        )
        job = {
            "id": "job-1",
            "status": "running",
            "updated_at": old.isoformat(),
            "items": [{"updated_at": old.isoformat()}],
        }

        self.assertTrue(api._job_is_stale(job))

    def test_terminal_job_is_never_stale(self):
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=api.STALE_JOB_MINUTES + 1
        )
        job = {
            "id": "job-1",
            "status": "cancelled",
            "updated_at": old.isoformat(),
            "items": [{"updated_at": old.isoformat()}],
        }

        self.assertFalse(api._job_is_stale(job))

    def test_recent_item_update_keeps_job_active(self):
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=api.STALE_JOB_MINUTES + 1
        )
        recent = datetime.datetime.now(datetime.timezone.utc)
        job = {
            "id": "job-1",
            "status": "running",
            "updated_at": old.isoformat(),
            "items": [{"updated_at": recent.isoformat()}],
        }

        self.assertFalse(api._job_is_stale(job))


if __name__ == "__main__":
    unittest.main()
