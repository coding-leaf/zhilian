import unittest

from tooling.subagent_stats import (
    _extract_tokens,
    format_compact_num,
    format_duration,
    format_model_name,
    format_num,
    format_rate,
    render_table,
)


class TestSubagentStats(unittest.TestCase):
    def test_extract_tokens(self):
        # 空数据防御
        self.assertEqual(_extract_tokens(None), (0, 0, 0, 0))
        self.assertEqual(_extract_tokens({}), (0, 0, 0, 0))

        # 完整数据
        data = {
            "tokens_input": 100,
            "tokens_cache_read": 500,
            "tokens_output": 50,
            "tokens_reasoning": 20,
        }
        self.assertEqual(_extract_tokens(data), (100, 500, 50, 20))

    def test_format_num(self):
        self.assertEqual(format_num(None), "0")
        self.assertEqual(format_num(0), "0")
        self.assertEqual(format_num(999), "999")
        self.assertEqual(format_num(15_000), "15,000 (15.0k)")
        self.assertEqual(format_num(2_500_000), "2,500,000 (2.50M)")

    def test_format_compact_num(self):
        self.assertEqual(format_compact_num(None), "0")
        self.assertEqual(format_compact_num(0), "0")
        self.assertEqual(format_compact_num(1234), "1,234")

    def test_format_rate(self):
        self.assertEqual(format_rate(0, 0), "0.0%")
        # 80 / 100 = 80.0%
        self.assertIn("80.0%", format_rate(80, 20))
        # 50 / 100 = 50.0%
        self.assertIn("50.0%", format_rate(50, 50))
        # 10 / 100 = 10.0%
        self.assertIn("10.0%", format_rate(10, 90))

    def test_format_duration(self):
        self.assertEqual(format_duration(None, None), "-")
        self.assertEqual(format_duration(1000, 500), "-")
        self.assertEqual(format_duration(1000, 1500), "0.5s")
        self.assertEqual(format_duration(1000, 65000), "1.1m")

    def test_format_model_name(self):
        self.assertEqual(format_model_name(None), "-")
        self.assertEqual(format_model_name("gpt-4o"), "gpt-4o")
        self.assertEqual(format_model_name('{"id": "claude-3-5-sonnet"}'), "claude-3-5-sonnet")

    def test_render_table(self):
        headers = ["ColA", "ColB"]
        rows = [["val1", "10"], ["val2", "20"]]
        alignments = ["left", "right"]
        total_row = ["TOTAL", "30"]

        table_str = render_table(headers, rows, alignments, total_row=total_row)
        self.assertIn("ColA", table_str)
        self.assertIn("ColB", table_str)
        self.assertIn("val1", table_str)
        self.assertIn("TOTAL", table_str)
        self.assertIn("┌", table_str)
        self.assertIn("└", table_str)


if __name__ == "__main__":
    unittest.main()
