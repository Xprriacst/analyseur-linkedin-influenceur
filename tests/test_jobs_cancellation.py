import unittest
from unittest.mock import patch

import src.jobs as jobs


class JobCancellationTest(unittest.TestCase):
    def test_process_job_preserves_cancelled_status_after_inflight_result(self):
        job = {
            "id": "job-1",
            "limit_posts": 25,
            "use_cache": True,
            "run_llm": False,
            "items": [
                {
                    "id": "item-1",
                    "url": "https://www.linkedin.com/in/yannrousseau/",
                    "status": "running",
                }
            ],
        }
        job_updates = []
        item_updates = []

        with (
            patch.object(jobs.db, "get_job", return_value=job),
            patch.object(
                jobs.db,
                "get_job_status",
                side_effect=["running", "running", "cancelled", "cancelled"],
            ),
            patch.object(jobs.db, "update_job", side_effect=lambda *args, **kwargs: job_updates.append(kwargs)),
            patch.object(jobs.db, "update_job_item", side_effect=lambda *args, **kwargs: item_updates.append(kwargs)),
            patch.object(jobs.db, "save_analysis") as save_analysis,
            patch.object(
                jobs,
                "run_analysis",
                return_value={
                    "handle": "yannrousseau",
                    "profile": {"name": "Yann Rousseau"},
                    "stats": {"count": 10},
                },
            ),
        ):
            jobs.process_job("token", "job-1")

        save_analysis.assert_not_called()
        self.assertIn({"status": "cancelled"}, item_updates)
        self.assertEqual(job_updates[-1]["status"], "cancelled")
        self.assertEqual(job_updates[-1]["completed"], 0)
        self.assertEqual(job_updates[-1]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
