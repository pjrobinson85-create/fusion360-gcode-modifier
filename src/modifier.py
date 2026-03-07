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
            t = parsed_line['tokens']
            return t.get('M') in [2.0, 30.0]

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
                self._update_state(parsed)
                parsed = self._optimize_rapids(parsed)
                
            output_lines.append(GcodeParser.rebuild_line(parsed))
            
        return output_lines
        
    def _update_state(self, parsed: dict):
        """Updates the virtual machine state based on the current line."""
        tokens = parsed['tokens']
        
        # Track position
        x = tokens.get('X')
        y = tokens.get('Y')
        z = tokens.get('Z')
        if any(val is not None for val in [x, y, z]):
            self.state.update_position(x, y, z)
            
        # Track feedrate
        if 'F' in tokens:
            self.state.feedrate = tokens['F']

    def _optimize_rapids(self, parsed: dict) -> dict:
        """Examines a G01 move and converts it to G00 if it meets safety criteria."""
        tokens = parsed['tokens']
        
        # We only care about converting G01 moves
        if tokens.get('G') != 1.0:
            return parsed
            
        # If we don't know where the machine is, it's not safe to optimize
        if not self.state.is_valid_position():
            return parsed

        feedrate = tokens.get('F', self.state.feedrate)
        if feedrate is None:
            return parsed

        # Rule 1: High-feedrate X/Y horizontal moves at or above the Safe Z clearance plane
        if 'X' in tokens or 'Y' in tokens:
            if self.state.position['Z'] >= self.config.safe_z_height:
                if feedrate >= self.config.xy_rapid_threshold:
                    tokens['G'] = 0.0 # Convert to Rapid
                    if 'F' in tokens:
                        del tokens['F'] # Rapids don't need feedrates
                    return parsed
                    
        # Rule 2: High-feedrate purely vertical Z retracts
        if 'Z' in tokens and 'X' not in tokens and 'Y' not in tokens:
            # We only convert retracts (Z moving UP)
            if tokens['Z'] > self.state.position['Z']:
                if feedrate >= self.config.z_rapid_threshold:
                    tokens['G'] = 0.0
                    if 'F' in tokens:
                        del tokens['F']
                    return parsed

        return parsed
