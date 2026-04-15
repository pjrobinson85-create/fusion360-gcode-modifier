"""
Tests for GcodeModifier — rapid detection, modal recovery, stitching, and bug regressions.

Config used throughout: safe_z=5.0, xy/z threshold=500 mm/min.
A move is a candidate for G0 conversion when:
  - Motion is G1 (explicit or modal)
  - Current Z >= 5.0 AND target Z >= 5.0  (for X/Y moves)
  - Feedrate >= 500
"""
import json
import os
import tempfile
import pytest

from src.config import ConfigManager
from src.modifier import GcodeModifier
from src.parser import GcodeParser
from src.state import MachineState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def make_config(safe_z=5.0, clearance=0.5, xy_threshold=500, z_threshold=500):
    """Create a temporary ConfigManager with controlled test values."""
    cfg = {
        "safe_z_height": safe_z,
        "clearance_height": clearance,
        "rapid_feedrate_thresholds": {
            "X_Y_RAPID": xy_threshold,
            "Z_RAPID": z_threshold,
        },
        "tool_change_position": {"X": 0.0, "Y": 0.0, "Z": 50.0},
        "tools": [],
    }
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(cfg, f)
    f.close()
    return ConfigManager(f.name), f.name


def process(lines, safe_z=5.0, clearance=0.5, xy_threshold=500, z_threshold=500):
    """Helper: run process_lines on a list of strings, return output lines."""
    config, tmp = make_config(safe_z, clearance, xy_threshold, z_threshold)
    try:
        modifier = GcodeModifier(config)
        return modifier.process_lines(lines)
    finally:
        os.unlink(tmp)


def tokens_of(line_str):
    """Return a letter→value dict for a G-code line string."""
    return {t['letter']: t['value'] for t in GcodeParser.parse_line(line_str)['tokens']}


# ---------------------------------------------------------------------------
# Core rapid-detection logic
# ---------------------------------------------------------------------------

class TestOptimiseXYRapids:
    def _setup_above_safe_z(self):
        """Return lines that establish a known position well above safe_z=5."""
        return [
            "G90",
            "G0 X0. Y0. Z10.",  # Z=10 > safe_z=5, all axes known
        ]

    def test_high_feedrate_xy_at_safe_z_converts_to_g0(self):
        lines = self._setup_above_safe_z() + ["G1 X100. Y0. F600."]
        result = process(lines)
        move = result[-1]
        t = tokens_of(move)
        assert t.get('G') == 0.0, f"Expected G0, got: {move}"
        assert 'F' not in t, "Feedrate should be stripped from a rapid"

    def test_low_feedrate_xy_stays_g1(self):
        lines = self._setup_above_safe_z() + ["G1 X100. Y0. F300."]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0

    def test_travel_at_clearance_plane_converts_to_g0(self):
        """A move at the clearance plane (above workpiece, below safe_z) must
        still become a rapid — clearance_height (0.5mm) governs rapid detection,
        NOT safe_z_height (5mm) which is only for tool-change retracts."""
        lines = [
            "G90",
            "G0 X0. Y0. Z1.",   # Z=1 > clearance=0.5 but < safe_z=5
            "G1 X100. Y0. F600.",
        ]
        result = process(lines)   # clearance defaults to 0.5
        t = tokens_of(result[-1])
        assert t.get('G') == 0.0, \
            "Travel move at clearance plane should be converted to G0"

    def test_cutting_move_below_clearance_stays_g1(self):
        """A cutting move where the tool descends below clearance_height (into
        material) must never be converted to a rapid regardless of feedrate."""
        lines = [
            "G90",
            "G0 X0. Y0. Z1.",    # at clearance plane
            "G1 X50. Y0. Z-1. F600.",  # target Z=-1, below clearance=0.5
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0, \
            "Move descending below clearance plane must stay G1"

    def test_move_descending_into_cut_stays_g1(self):
        """X/Y move whose target Z descends below clearance_height (into material)
        must never become a rapid, even at a high feedrate."""
        lines = [
            "G90",
            "G0 X0. Y0. Z1.",          # at clearance plane
            "G1 X50. Y0. Z-0.5 F600.", # descending into material — target below clearance=0.5
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0

    def test_feedrate_exactly_at_threshold_converts(self):
        lines = self._setup_above_safe_z() + ["G1 X50. Y0. F500."]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 0.0

    def test_feedrate_just_below_threshold_stays_g1(self):
        lines = self._setup_above_safe_z() + ["G1 X50. Y0. F499."]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0


class TestOptimiseZRapids:
    def test_z_retract_above_current_converts_to_g0(self):
        lines = [
            "G90",
            "G0 X0. Y0. Z5.",   # Z=5 (at safe_z)
            "G1 Z20. F600.",     # pure Z retract upward
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 0.0

    def test_z_plunge_downward_stays_g1(self):
        lines = [
            "G90",
            "G0 X0. Y0. Z20.",
            "G1 Z2. F600.",      # plunge down
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0

    def test_z_retract_combined_with_xy_uses_xy_rule(self):
        """A move with both X/Y and Z is governed by the X/Y rule, not the Z-retract rule."""
        lines = [
            "G90",
            "G0 X0. Y0. Z10.",
            "G1 X50. Y0. Z15. F600.",
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 0.0


class TestModalMotion:
    def test_modal_g1_injects_g0(self):
        """No explicit G on the line — modal G1 should still trigger conversion."""
        lines = [
            "G90",
            "G1 X0. Y0. Z10. F600.",   # establishes position + modal G1
            "X100. Y0. F600.",          # modal, no G — should be converted
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 0.0

    def test_modal_recovery_restores_g1_after_injected_g0(self):
        """
        After the optimizer injects a G0 rapid, the output modal mode is G0.
        The very next cutting move (which doesn't become a rapid) must have
        an explicit G1 prepended to prevent the machine from treating it as a rapid.
        """
        lines = [
            "G90",
            "G1 X0. Y0. Z10. F600.",   # set position, modal G1
            "G1 X100. Y0. F600.",       # converted to G0 → output modal = G0
            "G1 X100. Y-1. F100.",      # low feed, below threshold → must restore G1
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0, f"Modal recovery failed: {result[-1]}"

    def test_g0_passthrough_unchanged(self):
        """Explicit G0 moves must never be modified."""
        lines = [
            "G90",
            "G0 X0. Y0. Z50.",
            "G0 X100. Y0.",
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 0.0

    def test_g2_arc_passthrough_unchanged(self):
        lines = [
            "G90",
            "G0 X0. Y0. Z10.",
            "G2 X10. Y10. I5. J0. F300.",
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 2.0

    def test_g3_arc_passthrough_unchanged(self):
        lines = [
            "G90",
            "G0 X0. Y0. Z10.",
            "G3 X10. Y10. I5. J0. F300.",
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 3.0


class TestSafetyGuards:
    def test_unknown_position_skips_optimisation(self):
        """No position established yet — optimizer must not guess."""
        lines = ["G1 X100. Y0. F600."]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0

    def test_g91_relative_mode_skips_optimisation(self):
        lines = [
            "G91",              # relative mode — position tracking disabled
            "G1 X10. F600.",
        ]
        result = process(lines)
        t = tokens_of(result[-1])
        assert t.get('G') == 1.0

    def test_g28_homing_passes_through_unchanged(self):
        lines = ["G28"]
        result = process(lines)
        assert 'G28' in result[-1] or tokens_of(result[-1]).get('G') == 28.0


# ---------------------------------------------------------------------------
# Regression tests for the three bugs fixed in the engine overhaul
# ---------------------------------------------------------------------------

class TestRegressions:
    def test_regression_modal_g1_f_token_not_corrupted(self):
        """
        Regression for the g_token_idx == -1 bug.
        When a modal G1 line is converted to G0, the F token must be removed,
        not have its value zeroed. The last token before the fix would be
        silently overwritten by tokens[-1]['value'] = 0.0.
        """
        lines = [
            "G90",
            "G1 X0. Y0. Z10. F600.",  # establish position + modal
            "X100. Y0. F600.",          # modal — F is the last token
        ]
        result = process(lines)
        converted = result[-1]
        t = tokens_of(converted)
        # Must be G0 and must have NO F token (not a zero F)
        assert t.get('G') == 0.0, f"Should be G0: {converted}"
        assert 'F' not in t, f"F should be stripped, not zeroed: {converted}"

    def test_regression_no_motion_mode_at_file_start(self):
        """
        Regression for the intended_g = None insertion bug.
        A file that starts without any G motion command must not crash or
        insert a null token into rebuild_line().
        """
        lines = [
            "G90",
            "X10. Y10. F600.",   # no G ever seen — intended_g is None
        ]
        # Should not raise, and output must be valid
        result = process(lines)
        assert len(result) == 2

    def test_regression_state_does_not_bleed_between_process_file_calls(self):
        """
        Regression for state persistence bug.
        Calling process_file() twice on the same modifier must give the same
        result as calling it fresh, not accumulate state from the first run.
        """
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)

            lines = [
                "G90\n",
                "G0 X0. Y0. Z10.\n",
                "G1 X100. Y0. F600.\n",
            ]

            with tempfile.NamedTemporaryFile(mode='w', suffix='.tap', delete=False) as fin:
                fin.writelines(lines)
                in_path = fin.name

            out1 = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
            out1.close()
            out2 = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
            out2.close()

            modifier.process_file(in_path, out1.name)
            modifier.process_file(in_path, out2.name)

            with open(out1.name) as f1, open(out2.name) as f2:
                assert f1.read() == f2.read(), "Second process_file call gave different output"
        finally:
            os.unlink(tmp)
            os.unlink(in_path)
            os.unlink(out1.name)
            os.unlink(out2.name)


# ---------------------------------------------------------------------------
# process_lines edge cases
# ---------------------------------------------------------------------------

class TestProcessLines:
    def test_empty_input(self):
        result = process([])
        assert result == []

    def test_blank_lines_preserved(self):
        lines = ["", "G90", ""]
        result = process(lines)
        assert len(result) == 3

    def test_comment_only_file(self):
        lines = ["; program header", "; tool: 6mm end mill"]
        result = process(lines)
        assert len(result) == 2
        for line in result:
            assert ';' in line

    def test_output_line_count_matches_input(self):
        lines = [
            "G90",
            "G0 X0. Y0. Z10.",
            "G1 X50. Y0. F600.",
            "G1 X0. Y0. F600.",
            "M30",
        ]
        result = process(lines)
        assert len(result) == len(lines)


# ---------------------------------------------------------------------------
# stitch_files
# ---------------------------------------------------------------------------

class TestStitchFiles:
    def _write_tap(self, lines):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.tap', delete=False)
        f.write('\n'.join(lines))
        f.close()
        return f.name

    def _read_output(self, path):
        with open(path) as f:
            return f.readlines()

    def test_strips_m30_from_intermediate_file(self):
        file_a = self._write_tap(["G90", "G0 X0. Y0. Z10.", "G1 X50. F600.", "M30"])
        file_b = self._write_tap(["G90", "G0 X0. Y0. Z10.", "G1 X20. F600.", "M30"])
        out = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
        out.close()
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)
            modifier.stitch_files([file_a, file_b], out.name)
            lines = self._read_output(out.name)
            content = ''.join(lines)
            # M30 should appear exactly once (the last file's)
            assert content.count('M30') == 1
        finally:
            for p in [file_a, file_b, out.name, tmp]:
                os.unlink(p)

    def test_injects_safety_block_between_files(self):
        file_a = self._write_tap(["G90", "G0 X0. Y0. Z10.", "M30"])
        file_b = self._write_tap(["G90", "G0 X0. Y0. Z10.", "M30"])
        out = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
        out.close()
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)
            modifier.stitch_files([file_a, file_b], out.name)
            lines = self._read_output(out.name)
            content = ''.join(lines)
            assert 'TOOL CHANGE SAFETY BLOCK' in content
            assert 'M05' in content
        finally:
            for p in [file_a, file_b, out.name, tmp]:
                os.unlink(p)

    def test_state_reset_between_files(self):
        """
        State from file A must not affect optimization in file B.
        Both files have identical content; they must produce identical output sections.
        """
        tap_content = ["G90", "G0 X0. Y0. Z10.", "G1 X50. Y0. F600.", "M30"]
        file_a = self._write_tap(tap_content)
        file_b = self._write_tap(tap_content)
        out = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
        out.close()
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)
            modifier.stitch_files([file_a, file_b], out.name)
            lines = [l.strip() for l in self._read_output(out.name) if l.strip()]

            # Find the G1 X50 line in both halves; both should be converted to G0
            motion_lines = [l for l in lines if 'X50' in l]
            assert len(motion_lines) == 2, f"Expected 2 X50 moves, got: {motion_lines}"
            for move in motion_lines:
                assert move.startswith('G0'), f"Expected G0 after state reset, got: {move}"
        finally:
            for p in [file_a, file_b, out.name, tmp]:
                os.unlink(p)

    def test_single_file_stitch_behaves_like_process_file(self):
        """Stitching a single file should not inject a safety block."""
        tap = self._write_tap(["G90", "G0 X0. Y0. Z10.", "G1 X50. F600.", "M30"])
        out = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
        out.close()
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)
            modifier.stitch_files([tap], out.name)
            content = open(out.name).read()
            assert 'TOOL CHANGE' not in content
        finally:
            for p in [tap, out.name, tmp]:
                os.unlink(p)

    def test_same_tool_skips_safety_block(self):
        """
        When both files use the same tool number (T2 M6), no safety block
        should be injected and the machine should continue without stopping.
        """
        file_a = self._write_tap(["T2 M6", "G90", "G0 X0. Y0. Z10.", "G1 X50. F600.", "M30"])
        file_b = self._write_tap(["T2 M6", "G90", "G0 X0. Y0. Z10.", "G1 X80. F600.", "M30"])
        out = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
        out.close()
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)
            modifier.stitch_files([file_a, file_b], out.name)
            content = open(out.name).read()
            assert 'TOOL CHANGE SAFETY BLOCK' not in content, \
                "Same-tool transition must not inject a safety block"
            assert 'no tool change required' in content.lower(), \
                "Expected continuation comment for same-tool transition"
        finally:
            for p in [file_a, file_b, out.name, tmp]:
                os.unlink(p)

    def test_same_tool_strips_m6(self):
        """
        For a same-tool continuation the redundant M6 in the second file must
        be stripped so M6Start.m1s is never triggered unnecessarily.
        """
        file_a = self._write_tap(["T2 M6", "G90", "G0 X0. Y0. Z10.", "M30"])
        file_b = self._write_tap(["T2 M6", "G90", "G0 X0. Y0. Z10.", "M30"])
        out = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
        out.close()
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)
            modifier.stitch_files([file_a, file_b], out.name)
            content = open(out.name).read()
            # File A's M6 must be present; file B's must be stripped.
            # Count only actual M6 tokens (not comment text containing 'M6').
            m6_count = sum(
                1 for line in content.splitlines()
                if not line.strip().startswith(';')
                and any(
                    t['letter'] == 'M' and t['value'] == 6.0
                    for t in GcodeParser.parse_line(line)['tokens']
                )
            )
            assert m6_count == 1, \
                f"Expected exactly 1 M6 in stitched output, found {m6_count}"
        finally:
            for p in [file_a, file_b, out.name, tmp]:
                os.unlink(p)

    def test_different_tool_injects_safety_block(self):
        """
        When files use different tool numbers the safety block must still be
        injected — regression guard for the same-tool detection logic.
        """
        file_a = self._write_tap(["T1 M6", "G90", "G0 X0. Y0. Z10.", "M30"])
        file_b = self._write_tap(["T2 M6", "G90", "G0 X0. Y0. Z10.", "M30"])
        out = tempfile.NamedTemporaryFile(suffix='.tap', delete=False)
        out.close()
        config, tmp = make_config()
        try:
            modifier = GcodeModifier(config)
            modifier.stitch_files([file_a, file_b], out.name)
            content = open(out.name).read()
            assert 'TOOL CHANGE SAFETY BLOCK' in content, \
                "Different-tool transition must inject safety block"
            assert 'M05' in content
        finally:
            for p in [file_a, file_b, out.name, tmp]:
                os.unlink(p)
