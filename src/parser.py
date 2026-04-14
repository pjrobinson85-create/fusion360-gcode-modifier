import re
from typing import Dict, Any

class GcodeParser:
    """Parses a raw string of gcode into a token list of commands and values."""
    
    # Matches comments like (T3 ...) or standalone semicolon comments
    COMMENT_PATTERN = re.compile(r'\(.*?\)|;.*')
    
    # Matches individual gcode letters and their numeric values (e.g., X12.5)
    TOKEN_PATTERN = re.compile(r'([A-Z])([-+]?\d*\.?\d+)')

    @staticmethod
    def parse_line(line: str) -> Dict[str, Any]:
        """
        Parses a single line of G-code.
        Returns a dictionary with:
        - 'raw': The original line string
        - 'comment': The extracted comment (if any)
        - 'tokens': A list of parse dicts (e.g., [{'letter': 'G', 'value': 1.0}])
        - 'is_empty': True if the line has no actionable commands
        """
        result = {
            'raw': line,
            'comment': '',
            'tokens': [],
            'is_empty': True
        }
        
        # Extract comment
        comment_match = GcodeParser.COMMENT_PATTERN.search(line)
        if comment_match:
            result['comment'] = comment_match.group(0).strip()
            # Remove comment from the line for parsing
            line_no_comment = line.replace(result['comment'], '').strip()
        else:
            line_no_comment = line.strip()

        # Parse tokens
        if line_no_comment:
            result['is_empty'] = False
            # Find all letter-number pairs
            for match in GcodeParser.TOKEN_PATTERN.finditer(line_no_comment.upper()):
                letter = match.group(1)
                value = float(match.group(2))
                result['tokens'].append({'letter': letter, 'value': value})
                
        return result

    @staticmethod
    def rebuild_line(parsed_data: Dict[str, Any]) -> str:
        """Reconstructs a G-code line from a parsed dictionary."""
        if parsed_data['is_empty'] and parsed_data['comment']:
            return parsed_data['comment']
            
        parts = []
        # Maintain exact original ordering of tokens
        for token in parsed_data['tokens']:
            key = token['letter']
            val = token['value']
            # Format to remove trailing zeros if it's an integer
            val_str = f"{val:g}"
            # G-code standard often requires decimal points even on integers
            if '.' not in val_str and key in ['X', 'Y', 'Z', 'I', 'J', 'K', 'F']:
                val_str += '.'
            parts.append(f"{key}{val_str}")
                
        line_str = " ".join(parts)
        if parsed_data['comment']:
            line_str += f" {parsed_data['comment']}"
            
        return line_str
