import unittest
from options_engine.config import Settings
class ConfigTests(unittest.TestCase):
    def test_live_is_locked(self):
        with self.assertRaises(ValueError): Settings(mode='live').validate()
    def test_paper_is_allowed(self): Settings(mode='paper').validate()
if __name__=='__main__': unittest.main()
