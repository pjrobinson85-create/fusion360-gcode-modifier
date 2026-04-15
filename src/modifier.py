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
        self.state = MachineState()  # Reset state so repeated calls on the same instance don't bleed
        with open(input_filepath, 'r') as infile:
            lines = infile.readlines()

        modified_lines = self.process_lines(lines)

        with open(output_filepath, 'w') as outfile:
            for line in modified_lines:
                outfile.write(line + '\n')

    def stitch_files(self, input_filepaths: list[str], output_filepath: str):
        """Processes and merges multiple G-code files.

        For transitions where the tool changes, a safety block is injected and
        the M6 macro runs normally.  For transitions where the tool stays the
        same, the safety block is skipped and the redundant M6 is stripped so
        the machine continues cutting without interruption.
        """
        all_output_lines = []

        def is_end_command(parsed_line):
            for t in parsed_line['tokens']:
                if t['letter'] == 'M' and t['value'] in [2.0, 30.0]:
                    return True
                if t['letter'] == 'G' and t['value'] == 28.0:
                    return True
            return False

        def is_tool_change_command(parsed_line):
            """True if the line contains an M6 (tool change) command."""
            return any(t['letter'] == 'M' and t['value'] == 6.0
                       for t in parsed_line['tokens'])

        # Read every file once up front so we can compare tool numbers
        # before deciding what to inject between them.
        file_data = []
        for filepath in input_filepaths:
            with open(filepath, 'r') as infile:
                lines = infile.readlines()
            file_data.append({
                'path': filepath,
                'lines': lines,
                'tool': self._get_tool_number(lines),
            })

        for i, data in enumerate(file_data):
            lines        = data['lines']
            is_last_file  = (i == len(file_data) - 1)
            is_first_file = (i == 0)

            prev_tool = file_data[i - 1]['tool'] if i > 0 else None
            curr_tool = data['tool']

            # A same-tool transition means the physical tool did not change —
            # no need to stop the machine or prompt the operator.
            same_tool = (
                not is_first_file
                and prev_tool is not None
                and curr_tool is not None
                and prev_tool == curr_tool
            )

            if not is_first_file:
                if same_tool:
                    # No tool change — just a separator comment, machine keeps going
                    all_output_lines.extend([
                        "",
                        f"; --- CONTINUING WITH TOOL T{curr_tool} (no tool change required) ---",
                        "",
                    ])
                else:
                    # Different tool — inject the safety block so M6Start.m1s runs cleanly
                    all_output_lines.extend([
                        "",
                        "; --- AUTO-INJECTED TOOL CHANGE SAFETY BLOCK ---",
                        "M05 ; Force spindle OFF prior to Fusion's M06 macro",
                        f"G0 Z{self.config.safe_z_height} ; Lift to Safe Z before move",
                        "; ----------------------------------------------",
                        "",
                    ])

            # Reset state for each file so position/modal tracking from a
            # previous file cannot bleed into the next one.
            self.state = MachineState()
            processed_lines = self.process_lines(lines)

            for line_str in processed_lines:
                parsed = GcodeParser.parse_line(line_str)

                # Strip end-of-program commands from all but the final file
                if not is_last_file and is_end_command(parsed):
                    continue

                # For same-tool continuations, strip the redundant M6 so
                # M6Start.m1s is not triggered unnecessarily.
                if same_tool and is_tool_change_command(parsed):
                    continue

                all_output_lines.append(line_str)

        with open(output_filepath, 'w') as outfile:
            for line in all_output_lines:
                outfile.write(line + '\n')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_tool_number(self, lines: list[str]) -> int | None:
        """Return the tool number from the first T[n] M6 line in a file, or None."""
        for line in lines:
            parsed = GcodeParser.parse_line(line)
            tokens = parsed['tokens']
            has_m6 = any(t['letter'] == 'M' and t['value'] == 6.0 for t in tokens)
            if has_m6:
                t_val = next((t['value'] for t in tokens if t['letter'] == 'T'), None)
                if t_val is not None:
                    return int(t_val)
        return None

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
        has_g28 = any(t['letter'] == 'G' and t['value'] == 28.0 for t in tokens)
        if has_g28: return

        for t in tokens:
            if t['letter'] == 'G' and t['value'] in [0.0, 1.0, 2.0, 3.0]:
                self.state.input_motion_mode = t['value']

    def _update_state(self, parsed: dict):
        """Updates the virtual machine state based on the current line (output state)."""
        tokens = parsed['tokens']

        has_g28 = any(t['letter'] == 'G' and t['value'] == 28.0 for t in tokens)
        if has_g28: return

        for t in tokens:
            if t['letter'] == 'G':
                if t['value'] == 90.0: self.state.mode = 'G90'
                elif t['value'] == 91.0: self.state.mode = 'G91'

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

        if any(t['letter'] == 'G' and t['value'] == 28.0 for t in tokens):
            return parsed

        explicit_g = next((t['value'] for t in tokens if t['letter'] == 'G' and t['value'] in [0.0, 1.0, 2.0, 3.0]), None)

        has_xyz_keys = {t['letter'] for t in tokens if t['letter'] in ['X', 'Y', 'Z']}

        intended_g = explicit_g if explicit_g is not None else self.state.input_motion_mode

        if intended_g is None or len(has_xyz_keys) == 0:
            return parsed

        if not self.state.is_valid_position():
            return parsed

        feed_token = next((t['value'] for t in tokens if t['letter'] == 'F'), None)
        feedrate = feed_token if feed_token is not None else self.state.feedrate

        if feedrate is None:
            return parsed

        convert_to_rapid = False

        if intended_g == 1.0:
            if 'X' in has_xyz_keys or 'Y' in has_xyz_keys:
                target_z = next((t['value'] for t in tokens if t['letter'] == 'Z'), self.state.position['Z'])
                if self.state.position['Z'] >= self.config.safe_z_height and target_z >= self.config.safe_z_height:
                    if feedrate >= self.config.xy_rapid_threshold:
                        convert_to_rapid = True

            if 'Z' in has_xyz_keys and 'X' not in has_xyz_keys and 'Y' not in has_xyz_keys:
                z_target = next((t['value'] for t in tokens if t['letter'] == 'Z'), None)
                if z_target is not None and z_target > self.state.position['Z']:
                    if feedrate >= self.config.z_rapid_threshold:
                        convert_to_rapid = True

        if convert_to_rapid:
            if explicit_g == 1.0:
                for t in tokens:
                    if t['letter'] == 'G' and t['value'] == 1.0:
                        t['value'] = 0.0
                        break
            else:
                tokens.insert(0, {'letter': 'G', 'value': 0.0})

            parsed['tokens'] = [t for t in tokens if t['letter'] != 'F']
        else:
            if self.state.motion_mode == 0.0 and explicit_g is None and intended_g is not None:
                tokens.insert(0, {'letter': 'G', 'value': intended_g})

        return parsed
