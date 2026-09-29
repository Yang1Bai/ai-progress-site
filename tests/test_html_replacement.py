import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fetch_content import replace_block


class HtmlReplacementTests(unittest.TestCase):
    def test_source_latex_and_backreferences_are_literal(self):
        start, end = '<!-- START -->', '<!-- END -->'
        inner = r'<p>\mathcal{O}(N\log^2 N), \1 and \g<1></p>'
        result = replace_block('before' + start + 'old' + end + 'after', start, end, inner)
        self.assertEqual(result, 'before' + start + '\n' + inner + '\n      ' + end + 'after')

    def test_missing_marker_fails(self):
        with self.assertRaises(RuntimeError):
            replace_block('unrelated', '<!-- START -->', '<!-- END -->', 'new')
