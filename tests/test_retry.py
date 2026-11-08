import asyncio
import unittest

from house_lights.retry import call_with_retry


class RetryTests(unittest.TestCase):
    def test_retries_then_succeeds(self) -> None:
        attempts = {"n": 0}

        async def flaky() -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise TimeoutError("down")
            return "ok"

        result = asyncio.run(call_with_retry(flaky, attempts=3, delay=0, label="flaky"))
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["n"], 3)

    def test_value_error_is_not_retried(self) -> None:
        attempts = {"n": 0}

        async def bad() -> None:
            attempts["n"] += 1
            raise ValueError("no")

        with self.assertRaises(ValueError):
            asyncio.run(call_with_retry(bad, attempts=3, delay=0, label="bad"))
        self.assertEqual(attempts["n"], 1)


if __name__ == "__main__":
    unittest.main()
