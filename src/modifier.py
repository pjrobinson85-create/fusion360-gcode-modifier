from src.parser import GcodeParser
from src.state import MachineState
from src.config import ConfigManager

class GcodeModifier:
    """Core engine that modifies G-code to restore missing rapids and inject tool changes."""
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.state = MachineState()
        
    def process_file(self, input_filepath: str, output_filepath: str):
        """Processes an input G-code file and writes the modified output."""
        with open(input_filepath, 'r') as infile:
            lines = infile.readlines()
            
        modified_lines = self.process_lines(lines)
        
        with open(output_filepath, 'w') as outfile:
            for line in modified_lines:
                outfile.write(line + '\n')

    def stitch_files(self, input_filepaths: list[str], output_filepath: str):
        """Processes and merges multiple G-code files, safely injecting tool changes and stripping intermediate M30s."""
        all_output_lines = []
        
        def is_end_command(parsed_line):
            for t in parsed_line['tokens']:
                # Strip End of Program
                if t['letter'] == 'M' and t['value'] in [2.0, 30.0]:
                    return True
                # Strip Machine Homing (G28) from intermediate transitions
                if t['letter'] == 'G' and t['value'] == 28.0:
                    return True
            return False

        for i, filepath in enumerate(input_filepaths):
            with open(filepath, 'r') as infile:
                lines = infile.readlines()
                
            is_last_file = (i == len(input_filepaths) - 1)
            is_first_file = (i == 0)
            
            if not is_first_file:
                all_output_lines.extend([
                    # Inject safety block between files
                    "",
                    "; --- AUTO-INJECTED TOOL CHANGE SAFETY BLOCK ---",
                    "M05 ; Force spindle OFF prior to Fusion's M06 macro",
                    f"G0 Z{self.config.safe_z_height} ; Lift to Safe Z before move",
                    "; ----------------------------------------------",
                    ""
                ])

            processed_lines = self.process_lines(lines)
            
            for line_str in processed_lines:
                parsed = GcodeParser.parse_line(line_str)
                # Strip End of Program blocks from all but the final file
                if not is_last_file and is_end_command(parsed):
                    continue
                all_output_lines.append(line_str)
                
        with open(output_filepath, 'w') as outfile:
            for line in all_output_lines:
                outfile.write(line + '\n')

    def process_lines(self, lines: list[str]) -> list[str]:
        output_lines = []
        for raw_line in lines:
            parsed = GcodeParser.parse_line(raw_line)
            
            if not parsed['is_empty']:
                # Update input modal state before we optimize
                self._update_input_state(parsed)
                
                parsed = self._optimize_rapids(parsed)
                self._update_state(parsed)
                
            output_lines.append(GcodeParser.rebuild_line(parsed))
            
        return output_lines

    def _update_input_state(self, parsed: dict):
        """Tracks the modal state of the original input file."""
        tokens = parsed['tokens']
        # Ignore machine homing and relative moves for position tracking
        has_g28 = any(t['letter'] == 'G' and t['value'] == 28.0 for t in tokens)
        if has_g28: return

        for t in tokens:
            if t['letter'] == 'G' and t['value'] in [0.0, 1.0, 2.0, 3.0]:
                self.state.input_motion_mode = t['value']
        
    def _update_state(self, parsed: dict):
        """Updates the virtual machine state based on the current line (output state)."""
        tokens = parsed['tokens']
        
        # Ignore machine homing for position tracking
        has_g28 = any(t['letter'] == 'G' and t['value'] == 28.0 for t in tokens)
        if has_g28: return

        # Track Mode (Absolute vs Relative)
        for t in tokens:
            if t['letter'] == 'G':
                if t['value'] == 90.0: self.state.mode = 'G90'
                elif t['value'] == 91.0: self.state.mode = 'G91'

        # We only track positions in Absolute mode
        if self.state.mode != 'G90':
            return

        x, y, z = None, None, None
        for t in tokens:
            letter = t['letter']
            val = t['value']
            if letter == 'X': x = val
            elif letter == 'Y': y = val
            elif letter == 'Z': z = val
            elif letter == 'F': self.state.feedrate = val
            elif letter == 'G' and val in [0.0, 1.0, 2.0, 3.0]:
                self.state.motion_mode = val
                
        if any(val is not None for val in [x, y, z]):
            self.state.update_position(x, y, z)

    def _optimize_rapids(self, parsed: dict) -> dict:
        """Examines a motion move and converts it to G00 if safe, OR restores G01 if returning from a rapid."""
        tokens = parsed['tokens']
        
        # Block optimization and restoration on homing moves
        if any(t['letter'] == 'G' and t['value'] == 28.0 for t in tokens):
            return parsed

        explicit_g = next((t['value'] for t in tokens if t['letter'] == 'G' and t['value'] in [0.0, 1.0, 2.0, 3.0]), None)
        g_token_idx = next((i for i, t in enumerate(tokens) if t['letter'] == 'G' and t['value'] == explicit_g), -1)
        
        has_xyz_keys = {t['letter'] for t in tokens if t['letter'] in ['X', 'Y', 'Z']}
        
        # Determine the INTENDED motion mode for this line based on the input stream
        intended_g = explicit_g if explicit_g is not None else self.state.input_motion_mode
        
        # We only consider optimizing G1 moves. G0, G2, G3 are passed as-is.
        # However, we MUST handle the case where we previously injected a G0 and now need to restore the intended mode.
        if intended_g is None or len(has_xyz_keys) == 0:
            return parsed

        # If we don't know where the machine is, it's not safe to optimize
        if not self.state.is_valid_position():
            return parsed

        feed_token = next((t['value'] for t in tokens if t['letter'] == 'F'), None)
        feedrate = feed_token if feed_token is not None else self.state.feedrate
        
        if feedrate is None:
            return parsed

        convert_to_rapid = False

        if intended_g == 1.0:
            # Rule 1: High-feedrate X/Y horizontal moves at or above the Safe Z clearance plane
            if 'X' in has_xyz_keys or 'Y' in has_xyz_keys:
                target_z = next((t['value'] for t in tokens if t['letter'] == 'Z'), self.state.position['Z'])
                if self.state.position['Z'] >= self.config.safe_z_height and target_z >= self.config.safe_z_height:
                    if feedrate >= self.config.xy_rapid_threshold:
                        convert_to_rapid = True
                        
            # Rule 2: High-feedrate purely vertical Z retracts
            if 'Z' in has_xyz_keys and 'X' not in has_xyz_keys and 'Y' not in has_xyz_keys:
                z_target = next((t['value'] for t in tokens if t['letter'] == 'Z'), None)
                if z_target is not None and z_target > self.state.position['Z']:
                    if feedrate >= self.config.z_rapid_threshold:
                        convert_to_rapid = True

        if convert_to_rapid:
            if explicit_g == 1.0:
                tokens[g_token_idx]['value'] = 0.0
            else:
                # Inject G0 at the start of the token list
                tokens.insert(0, {'letter': 'G', 'value': 0.0})
                
            # Remove F token from the optimized rapid line
            parsed['tokens'] = [t for t in tokens if t['letter'] != 'F']
            # Note: We don't update self.state.motion_mode here, _update_state will handle it.
        else:
            # SAFETY RECOVERY: If we are NOT converting to rapid, but our OUTPUT state is currently G0,
            # we MUST restore the intended mode (usually G1, G2, or G3) to prevent a modal rapid crash.
            if self.state.motion_mode == 0.0 and explicit_g is None:
                tokens.insert(0, {'letter': 'G', 'value': intended_g})

        return parsed
