import os
from flask import Flask, request, render_template, send_file, jsonify
from werkzeug.utils import secure_filename
import traceback

# Import our engine
from src.config import ConfigManager
from src.modifier import GcodeModifier

app = Flask(__name__)

# Configure upload and output folders
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), 'outputs')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max limit

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.route('/')
def index():
    """Renders the drag-and-drop upload interface."""
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handles the file upload, processes it, and returns the download URL."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and (file.filename.endswith('.nc') or file.filename.endswith('.tap')):
        try:
            filename = secure_filename(file.filename)
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Generate the output filename
            name, ext = os.path.splitext(filename)
            output_filename = f"{name}_optimized{ext}"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            
            # Save the original file
            file.save(input_path)
            
            # Process the file via the engine
            config = ConfigManager()
            modifier = GcodeModifier(config)
            modifier.process_file(input_path, output_path)
            
            # Return success and the download URL
            return jsonify({
                'success': True,
                'message': 'File processed successfully!',
                'download_url': f'/api/download/{output_filename}',
                'filename': output_filename
            })
            
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
            
    return jsonify({'error': 'Invalid file type. Please upload a .nc or .tap file.'}), 400

@app.route('/api/stitch', methods=['POST'])
def stitch_files():
    """Handles multiple file uploads and stitches them together for tool changes."""
    if 'files[]' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
        
    files = request.files.getlist('files[]')
    if not files or len(files) == 0:
        return jsonify({'error': 'No selected files'}), 400
        
    try:
        filepaths = []
        for f in files:
            if f and (f.filename.endswith('.nc') or f.filename.endswith('.tap')):
                filename = secure_filename(f.filename)
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                f.save(path)
                filepaths.append(path)
                
        if not filepaths:
            return jsonify({'error': 'Invalid file types. Please upload .nc or .tap files.'}), 400
            
        output_filename = "Master_Job_Optimized.nc"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        config = ConfigManager()
        modifier = GcodeModifier(config)
        modifier.stitch_files(filepaths, output_path)
        
        return jsonify({
            'success': True,
            'message': 'Files stitched and optimized!',
            'download_url': f'/api/download/{output_filename}',
            'filename': output_filename
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>', methods=['GET'])
def download_file(filename):
    """Serves the optimized file back to the user."""
    safe_filename = secure_filename(filename)
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], safe_filename)
    
    if os.path.exists(output_path):
        return send_file(output_path, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    # Initialize the engine once to ensure config is available
    config = ConfigManager()
    print(f"Server starting. Safe Z-Height is set to: {config.safe_z_height}mm")
    app.run(debug=True, host='0.0.0.0', port=5005)
