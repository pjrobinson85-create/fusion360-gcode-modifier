import argparse
import sys
import os
from src.config import ConfigManager
from src.modifier import GcodeModifier

def main():
    parser = argparse.ArgumentParser(description="Fusion 360 Gcode Modifier MVP")
    parser.add_argument("input", help="Path to the input .nc or .tap file")
    parser.add_argument("output", help="Path to save the modified output file")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Error: Could not find input file: {args.input}")
        sys.exit(1)
        
    output_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading configuration...")
    config = ConfigManager()
    
    print(f"Initializing Geometry Engine...")
    modifier = GcodeModifier(config)
    
    print(f"Processing {args.input}...")
    modifier.process_file(args.input, args.output)
    
    print(f"Success! Optimized Gcode saved to {args.output}")

if __name__ == "__main__":
    main()
