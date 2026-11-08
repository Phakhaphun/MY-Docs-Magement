"""Keep the benchmark's Unicode/error scoring honest, especially for Thai."""
import unittest
from tools.benchmark_ocr_quality import edit_distance,normalized


class OCRQualityMetricTests(unittest.TestCase):
    def test_equivalent_thai_sara_am_and_whitespace_are_not_ocr_errors(self):
        self.assertEqual(normalized('จำนวนเงิน'),normalized('จํานวนเงิน'))
        self.assertEqual(normalized('AB 123\n45'),normalized('AB12345'))

    def test_letter_case_punctuation_and_digits_still_count_as_errors(self):
        self.assertNotEqual(normalized('Invoice'),normalized('invoice'))
        self.assertEqual(edit_distance(normalized('1,250.50'),normalized('1.250.50')),1)
        self.assertEqual(edit_distance('12345','1234'),1)
        self.assertEqual(edit_distance('12345','012345'),1)

    def test_empty_or_completely_missing_output_is_scored_as_missing_text(self):
        self.assertEqual(edit_distance('abcdef',''),6)
        self.assertEqual(edit_distance('','abc'),3)
        self.assertEqual(edit_distance('ภาษาไทย','ภาษาไทย'),0)
