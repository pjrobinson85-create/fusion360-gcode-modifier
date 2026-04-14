"""
Tests for MachineState — position tracking, cloning, validity checks.
"""
from src.state import MachineState


class TestMachineState:
    def test_initial_position_is_invalid(self):
        state = MachineState()
        assert state.is_valid_position() is False

    def test_partial_position_still_invalid(self):
        state = MachineState()
        state.update_position(x=10.0, y=20.0)
        assert state.is_valid_position() is False

    def test_all_axes_set_is_valid(self):
        state = MachineState()
        state.update_position(x=0.0, y=0.0, z=5.0)
        assert state.is_valid_position() is True

    def test_update_position_partial_preserves_existing(self):
        state = MachineState()
        state.update_position(x=10.0, y=20.0, z=5.0)
        state.update_position(x=50.0)  # only update X
        assert state.position['X'] == 50.0
        assert state.position['Y'] == 20.0  # unchanged
        assert state.position['Z'] == 5.0   # unchanged

    def test_update_position_z_only(self):
        state = MachineState()
        state.update_position(x=0.0, y=0.0, z=0.0)
        state.update_position(z=25.0)
        assert state.position['Z'] == 25.0

    def test_clone_is_independent(self):
        state = MachineState()
        state.update_position(x=10.0, y=20.0, z=5.0)
        state.motion_mode = 1.0
        state.feedrate = 600.0

        clone = state.clone()
        # Mutate clone — original must be unaffected
        clone.position['X'] = 999.0
        clone.motion_mode = 0.0
        clone.feedrate = 100.0

        assert state.position['X'] == 10.0
        assert state.motion_mode == 1.0
        assert state.feedrate == 600.0

    def test_clone_copies_all_fields(self):
        state = MachineState()
        state.update_position(x=1.0, y=2.0, z=3.0)
        state.mode = 'G91'
        state.motion_mode = 1.0
        state.input_motion_mode = 1.0
        state.feedrate = 300.0
        state.spindle_state = 'M03'
        state.active_tool = 2
        state.coolant_state = 'M08'

        clone = state.clone()
        assert clone.position == {'X': 1.0, 'Y': 2.0, 'Z': 3.0}
        assert clone.mode == 'G91'
        assert clone.motion_mode == 1.0
        assert clone.input_motion_mode == 1.0
        assert clone.feedrate == 300.0
        assert clone.spindle_state == 'M03'
        assert clone.active_tool == 2
        assert clone.coolant_state == 'M08'

    def test_default_mode_is_absolute(self):
        state = MachineState()
        assert state.mode == 'G90'

    def test_default_motion_mode_is_none(self):
        state = MachineState()
        assert state.motion_mode is None
        assert state.input_motion_mode is None
