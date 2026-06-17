import unittest
from unittest.mock import patch

import src.zernio as zernio


class ZernioCreatePostTest(unittest.TestCase):
    def test_publish_payload_uses_publish_now(self):
        with patch.object(zernio, "_request", return_value={"post": {"_id": "post-1"}}) as request:
            result = zernio.create_post("Hello LinkedIn", "account-1")

        self.assertEqual(result, {"post": {"_id": "post-1"}})
        self.assertEqual(request.call_args.args, ("POST", "/posts"))
        body = request.call_args.kwargs["body"]
        self.assertEqual(body["content"], "Hello LinkedIn")
        self.assertEqual(body["platforms"], [{"platform": "linkedin", "accountId": "account-1"}])
        self.assertTrue(body["publishNow"])
        self.assertNotIn("isDraft", body)

    def test_draft_payload_uses_is_draft(self):
        with patch.object(zernio, "_request", return_value={"post": {"_id": "post-2"}}) as request:
            result = zernio.create_post("Draft me", "account-2", is_draft=True)

        self.assertEqual(result, {"post": {"_id": "post-2"}})
        self.assertEqual(request.call_args.args, ("POST", "/posts"))
        body = request.call_args.kwargs["body"]
        self.assertEqual(body["content"], "Draft me")
        self.assertEqual(body["platforms"], [{"platform": "linkedin", "accountId": "account-2"}])
        self.assertTrue(body["isDraft"])
        self.assertNotIn("publishNow", body)


if __name__ == "__main__":
    unittest.main()
