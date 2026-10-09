"""Shared test-environment setup."""

import os
import time


# The test expectations use UTC for local-time conversions. Keep test results
# independent of the timezone configured by the host or CI runner.
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()
