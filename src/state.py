class MachineState:
    """Tracks the continuous state of the CNC machine throughout the gcode execution."""
    
    def __init__(self):
        self.position = {'X': None, 'Y': None, 'Z': None}
        self.mode = 'G90'  # Default to Absolute coordinate mode
        self.motion_mode = None  # Tracks modal G0, G1, G2, G3 in the OUTPUT 
        self.input_motion_mode = None  # Tracks modal G in the INPUT
        self.feedrate = None
        self.spindle_state = 'M05' # Off by default
        self.active_tool = None
        self.coolant_state = 'M09' # Off by default

    def update_position(self, x=None, y=None, z=None):
        if x is not None: self.position['X'] = float(x)
        if y is not None: self.position['Y'] = float(y)
        if z is not None: self.position['Z'] = float(z)

    def is_valid_position(self) -> bool:
        """Returns True if the machine has established X, Y, and Z coordinates."""
        return all(v is not None for v in self.position.values())
        
    def clone(self):
        """Creates a snapshot of the current state."""
        new_state = MachineState()
        new_state.position = dict(self.position)
        new_state.mode = self.mode
        new_state.motion_mode = self.motion_mode
        new_state.input_motion_mode = self.input_motion_mode
        new_state.feedrate = self.feedrate
        new_state.spindle_state = self.spindle_state
        new_state.active_tool = self.active_tool
        new_state.coolant_state = self.coolant_state
        return new_state
