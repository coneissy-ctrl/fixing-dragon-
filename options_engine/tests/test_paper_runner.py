import unittest
from options_engine.paper_runner import run

class PaperRunnerTests(unittest.TestCase):
    def test_full_paper_lifecycle_smoke(self):
        self.assertEqual(run(), 0)

if __name__ == '__main__': unittest.main()
