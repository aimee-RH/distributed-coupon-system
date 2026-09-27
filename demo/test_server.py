import concurrent.futures
import unittest

from server import CouponDemo


class CouponDemoTest(unittest.TestCase):
    def test_failed_write_releases_reservation_for_retry(self):
        coupon = CouponDemo(1)
        self.assertEqual(coupon.redeem("alice", fail_db=True), "rolled_back")
        self.assertEqual(coupon.redeem("alice"), "issued")
        self.assertEqual(coupon.state()["conservation_gap"], 0)
        self.assertEqual(coupon.state()["cache_stock"], 0)

    def test_concurrent_requests_do_not_oversell_or_duplicate(self):
        coupon = CouponDemo(5)
        users = [f"user-{i % 20}" for i in range(100)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(coupon.redeem, users))
        self.assertEqual(results.count("issued"), 5)
        self.assertEqual(coupon.state()["issued_count"], 5)
        self.assertEqual(coupon.state()["db_stock"], 0)
        self.assertEqual(coupon.state()["conservation_gap"], 0)


if __name__ == "__main__":
    unittest.main()
