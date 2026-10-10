"""Python facade over the built CLI; standard library only."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from packer_adapter import validation_ordinary  # noqa: E402
from packer_adapter.client import Packer, PackerError, default_binary  # noqa: E402


@unittest.skipUnless(default_binary().exists(), 'Build the native CLI first')
class ClientTests(unittest.TestCase):
    def test_pack_round_trip_matches_validator(self):
        packer = Packer().add_box(id='carton', width=100, length=60, height=40)
        packer.add_item(id='a', width=50, length=30, height=20, quantity=5, rotation='any', diagonal=False)
        packer.set_options(time_limit_ms=500).set_options(improve=True)
        result = packer.pack()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['support_mode'], 'stable')
        self.assertTrue(result['stats']['proven_optimal'])
        self.assertEqual(validation_ordinary.validate(packer.request(), result), [])

    def test_full_base_and_errors(self):
        packer = Packer().add_box({'id': 'b', 'width': 10, 'length': 10, 'height': 10})
        packer.add_item({'id': 'x', 'width': 5, 'length': 5, 'height': 5}, quantity=2)
        result = packer.set_options(support_mode='full_base').pack()
        self.assertEqual(result['support_mode'], 'full_base')
        with self.assertRaisesRegex(PackerError, 'support_mode'):
            packer.set_options(support_mode='floating').pack()
        with self.assertRaisesRegex(PackerError, 'missing'):
            Packer(binary=ROOT / 'missing-binary').pack()
        with self.assertRaises(ValueError):
            Packer(timeout=0)


if __name__ == '__main__':
    unittest.main()
