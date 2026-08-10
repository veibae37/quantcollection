import hashlib
import hmac
import unittest

from qmt_auth import resolve_qmt_webhook_secret


class QmtAuthTests(unittest.TestCase):
    def test_explicit_secret_takes_precedence(self):
        env = {"QMT_WEBHOOK_SECRET": "x" * 32, "BLOB_READ_WRITE_TOKEN": "blob-token"}
        self.assertEqual(resolve_qmt_webhook_secret(env), "x" * 32)

    def test_placeholder_falls_back_to_hmac_derivation(self):
        env = {
            "QMT_WEBHOOK_SECRET": "replace_with_at_least_24_random_characters",
            "BLOB_READ_WRITE_TOKEN": "blob-token",
        }
        expected = hmac.new(
            b"blob-token", b"quantcollection/qmt-webhook/v1", hashlib.sha256
        ).hexdigest()
        self.assertEqual(resolve_qmt_webhook_secret(env), expected)

    def test_missing_credentials_fail_closed(self):
        self.assertEqual(resolve_qmt_webhook_secret({}), "")


if __name__ == "__main__":
    unittest.main()
