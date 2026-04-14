# Fusion 360 G-Code Modifier (Hobby License Optimizer)

A powerful G-code post-processor and stitching engine designed to overcome the limitations of the Fusion 360 Hobby License. 

## 🚀 Key Features

- **Rapid Recovery (G0):** Automatically detects high-speed travel moves exported as `G1` and restores them to true `G0` rapid movements, significantly reducing machine cycle time.
- **Modal Safety Engine:** Tracks the machine state (modal modal) to ensure that `G1` cutting feeds are always restored after a rapid move, preventing accidental "rapid plunges" into material.
- **Ordered Parsing:** Preserves the exact order and duplication of G-code commands (e.g., `G17 G90 G94` setup blocks and `T# M6` tool changes).
- **Anti-Gouge Logic:** Strict geometry rules prevent "dog-leg" rapids. The engine only optimizes moves if both the start and end points are safely above the clearance plane.
- **Multi-File Stitching:** Merges multiple toolpaths into a single continuous job with Mach3-compatible tool change injections.
- **Transition Safety:** Automatically strips intermediate homing (`G28`) and program end (`M30`) commands from stitched files to prevent surface-dragging artifacts.
- **Safety Retracts:** Injects mandatory Z-retracts during tool transitions for real-world safety.

## ⚙️ Configuration

Settings are managed in `config/default_config.json`:

- `safe_z_height`: The elevation (in mm) at or above which it is safe to perform rapid traversals. (Default: `1.0`)
- `rapid_feedrate_thresholds`: The feedrates at or above which `G1` moves are considered candidates for optimization.
- `tool_change_position`: Preferred location for manual tool swaps.

## 🏁 Getting Started

### Web Interface
Run the Flask server for a drag-and-drop optimization experience:
```bash
python app.py
```
Visit `http://localhost:5005` in your browser.

### CLI Usage
For batch processing:
```bash
python cli.py input_file.nc output_file.tap
```

## 🛠 Project Structure

- `app.py`: Web server and UI logic.
- `src/modifier.py`: Core geometry and optimization engine.
- `src/parser.py`: Ordered G-code tokenization.
- `src/state.py`: Machine state and modal tracking.

## ⚠️ Disclaimer
Always dry-run generated G-code on your machine before cutting material. Ensure your post-processor settings and machine coordinates are consistent with the `safe_z_height` defined in the config.
