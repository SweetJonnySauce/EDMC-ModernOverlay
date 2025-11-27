import os
import pytest


def pytest_runtest_setup(item):
    if item.get_closest_marker("pyqt_required"):
        if not os.getenv("PYQT_TESTS"):
            pytest.skip("PYQT_TESTS not set; skipping PyQt-dependent test")
