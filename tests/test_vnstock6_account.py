import unittest

from scripts.verify_vnstock_account import verify_status


class VnstockAccountTest(unittest.TestCase):
    def test_accepts_silver_and_higher_without_exposing_device_or_key(self):
        result = verify_status({
            "authenticated": True,
            "tier": "silver",
            "expires_at": "2027-01-01",
            "device_id": "private-device",
            "api_key": "private-key",
        })

        self.assertEqual(result["tier"], "silver")
        self.assertNotIn("device_id", result)
        self.assertNotIn("api_key", result)

    def test_rejects_community_tier(self):
        with self.assertRaisesRegex(RuntimeError, "below the required"):
            verify_status({"authenticated": True, "tier": "free"})

    def test_rejects_unauthenticated_account(self):
        with self.assertRaisesRegex(RuntimeError, "not authenticated"):
            verify_status({"authenticated": False, "tier": "silver"})


if __name__ == "__main__":
    unittest.main()
