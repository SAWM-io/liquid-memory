import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hashlib
import bootstrap_sdk

class BootstrapTests(unittest.TestCase):
    def test_mismatch_never_replaces_existing_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "sdk.py"
            target.write_bytes(b"previous verified sdk")
            with self.assertRaises(ValueError):
                bootstrap_sdk.install(b"changed distribution", target)
            self.assertEqual(target.read_bytes(), b"previous verified sdk")

    def test_verified_bytes_are_written_exactly(self):
        data = b"test fixture, not the real SDK"
        with tempfile.TemporaryDirectory() as folder, patch.object(bootstrap_sdk, "SHA256", hashlib.sha256(data).hexdigest()):
            target = Path(folder) / "sdk.py"
            bootstrap_sdk.install(data, target)
            self.assertEqual(target.read_bytes(), data)
