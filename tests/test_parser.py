"""
Tests for GcodeParser — parse_line() and rebuild_line().
"""
import pytest
from src.parser import GcodeParser


class TestParseLine:
    def test_standard_g1_line(self):
        result = GcodeParser.parse_line("G1 X10.0 Y20.0 F600")
        assert result['is_empty'] is False
        assert result['comment'] == ''
        tokens = {t['letter']: t['value'] for t in result['tokens']}
        assert tokens['G'] == 1.0
        assert tokens['X'] == 10.0
        assert tokens['Y'] == 20.0
        assert tokens['F'] == 600.0

    def test_g0_rapid(self):
        result = GcodeParser.parse_line("G0 X0. Y0. Z50.")
        tokens = {t['letter']: t['value'] for t in result['tokens']}
        assert tokens['G'] == 0.0
        assert tokens['Z'] == 50.0

    def test_modal_move_no_g_token(self):
        """A line with only coordinates (no G) is valid modal G-code."""
        result = GcodeParser.parse_line("X50. Y30. F500")
        assert result['is_empty'] is False
        letters = [t['letter'] for t in result['tokens']]
        assert 'G' not in letters
        assert 'X' in letters

    def test_inline_parenthesis_comment(self):
        result = GcodeParser.parse_line("G1 X10. (this is a comment)")
        assert result['comment'] == '(this is a comment)'
        tokens = {t['letter']: t['value'] for t in result['tokens']}
        assert tokens['G'] == 1.0
        assert tokens['X'] == 10.0

    def test_semicolon_comment(self):
        result = GcodeParser.parse_line("G1 X10. ; rapid move")
        assert '; rapid move' in result['comment']
        assert result['is_empty'] is False

    def test_comment_only_line(self):
        result = GcodeParser.parse_line("; just a comment")
        assert result['is_empty'] is True
        assert result['comment'] != ''

    def test_empty_line(self):
        result = GcodeParser.parse_line("")
        assert result['is_empty'] is True
        assert result['tokens'] == []

    def test_blank_whitespace_line(self):
        result = GcodeParser.parse_line("   \t  ")
        assert result['is_empty'] is True

    def test_negative_coordinates(self):
        result = GcodeParser.parse_line("G1 X-10.5 Y-20.0")
        tokens = {t['letter']: t['value'] for t in result['tokens']}
        assert tokens['X'] == -10.5
        assert tokens['Y'] == -20.0

    def test_multiple_tokens_preserved(self):
        result = GcodeParser.parse_line("G1 X1. Y2. Z3. F400")
        assert len(result['tokens']) == 5  # G, X, Y, Z, F

    def test_m_code(self):
        result = GcodeParser.parse_line("M05")
        tokens = {t['letter']: t['value'] for t in result['tokens']}
        assert tokens['M'] == 5.0

    def test_lowercase_input_normalised(self):
        result = GcodeParser.parse_line("g1 x10.0 y5.0")
        tokens = {t['letter']: t['value'] for t in result['tokens']}
        assert tokens.get('G') == 1.0

    def test_token_order_preserved(self):
        result = GcodeParser.parse_line("G1 X10. Y20. Z5. F600")
        letters = [t['letter'] for t in result['tokens']]
        assert letters == ['G', 'X', 'Y', 'Z', 'F']

    def test_raw_field_preserved(self):
        line = "G1 X10.0 Y20.0"
        result = GcodeParser.parse_line(line)
        assert result['raw'] == line


class TestRebuildLine:
    def test_round_trip_g1(self):
        line = "G1 X10. Y20. F600."
        result = GcodeParser.parse_line(line)
        rebuilt = GcodeParser.rebuild_line(result)
        # Re-parse rebuilt output and confirm same tokens
        re_parsed = GcodeParser.parse_line(rebuilt)
        orig_tokens = {t['letter']: t['value'] for t in result['tokens']}
        rebuilt_tokens = {t['letter']: t['value'] for t in re_parsed['tokens']}
        assert orig_tokens == rebuilt_tokens

    def test_round_trip_with_comment(self):
        line = "G1 X5. (cutting move)"
        result = GcodeParser.parse_line(line)
        rebuilt = GcodeParser.rebuild_line(result)
        assert '(cutting move)' in rebuilt
        assert 'G1' in rebuilt

    def test_adds_decimal_to_coordinate_integers(self):
        result = GcodeParser.parse_line("G1 X10 Y20")
        rebuilt = GcodeParser.rebuild_line(result)
        # X and Y should have decimal points added
        assert 'X10.' in rebuilt
        assert 'Y20.' in rebuilt

    def test_no_decimal_on_g_code(self):
        result = GcodeParser.parse_line("G1 X10.")
        rebuilt = GcodeParser.rebuild_line(result)
        # G codes should not have trailing decimal
        assert 'G1 ' in rebuilt or rebuilt.startswith('G1')
        assert 'G1.' not in rebuilt

    def test_empty_line_with_comment_returns_comment(self):
        result = GcodeParser.parse_line("; program start")
        result['is_empty'] = True
        rebuilt = GcodeParser.rebuild_line(result)
        assert '; program start' in rebuilt

    def test_modified_token_reflected_in_output(self):
        """Mutating a token value should appear in the rebuilt line."""
        result = GcodeParser.parse_line("G1 X10. Y20.")
        for t in result['tokens']:
            if t['letter'] == 'G':
                t['value'] = 0.0
        rebuilt = GcodeParser.rebuild_line(result)
        assert rebuilt.startswith('G0')
