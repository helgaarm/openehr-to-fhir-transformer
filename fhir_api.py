#!/usr/bin/env python3
"""
Flask REST API for openEHR to FHIR transformation.
Accepts openEHR composition, mapping config, and optional patient demographics.
Returns a FHIR Bundle JSON.
"""

from flask import Flask, request, jsonify, Response
import json
import logging
from openEHR_to_FHIR_transformer import OpenEHRToFHIRTransformer

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure JSON to preserve Unicode characters instead of escaping them
app.config['JSON_AS_ASCII'] = False
app.json.ensure_ascii = False

# Configure max upload size (50MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'service': 'openEHR-to-FHIR-API'}), 200


@app.route('/', methods=['GET'])
def home():
    """Render a simple HTML upload form."""
    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>openEHR to FHIR Transformer</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .container { max-width: 700px; margin: auto; }
            h1 { color: #2c3e50; }
            label { display: block; margin-top: 20px; font-weight: bold; }
            input[type=file] { margin-top: 8px; }
            .option { display: flex; align-items: center; gap: 10px; margin-top: 20px; }
            .option label { margin-top: 0; font-weight: normal; }
            input[type=checkbox] { width: 18px; height: 18px; }
            button { margin-top: 20px; padding: 10px 20px; font-size: 16px; }
            .note { margin-top: 16px; color: #555; }
            .response { margin-top: 24px; white-space: pre-wrap; background: #f7f7f7; padding: 16px; border: 1px solid #ddd; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>openEHR to FHIR Transformer</h1>
            <p>Upload your openEHR composition, mapping, and optional demographics files.</p>
            <form id="uploadForm" method="post" enctype="multipart/form-data" action="/transform">
                <label for="composition">Composition JSON</label>
                <input type="file" id="composition" name="composition" accept="application/json" required>

                <label for="mapping">Mapping JSON</label>
                <input type="file" id="mapping" name="mapping" accept="application/json" required>

                <label for="demographics">Demographics JSON (optional)</label>
                <input type="file" id="demographics" name="demographics" accept="application/json">

                <div class="option">
                    <input type="checkbox" id="include_pdf" name="include_pdf" value="true">
                    <label for="include_pdf">Include generated PDF summary as DocumentReference</label>
                </div>

                <button type="submit">Transform to FHIR Bundle</button>
            </form>
            <div class="note">
                The resulting FHIR bundle JSON is returned directly by the API. If PDF is enabled, the bundle includes an embedded base64 PDF attachment in a DocumentReference resource.
            </div>
        </div>
    </body>
    </html>
    '''
    return Response(html, mimetype='text/html')


@app.route('/transform', methods=['POST'])
def transform():
    """
    Transform openEHR composition to FHIR Bundle.
    
    Accepts multipart form data:
    - composition: openEHR composition JSON file (required)
    - mapping: Mapping configuration JSON file (required)
    - demographics: Patient demographics JSON file (optional)
    
    Returns:
    - JSON response containing FHIR Bundle or error details
    """
    try:
        # Validate request has files
        if 'composition' not in request.files or 'mapping' not in request.files:
            return jsonify({
                'error': 'Missing required files',
                'required': ['composition', 'mapping'],
                'optional': ['demographics']
            }), 400
        
        composition_file = request.files['composition']
        mapping_file = request.files['mapping']
        demographics_file = request.files.get('demographics')
        
        # Validate file names are not empty
        if not composition_file.filename or not mapping_file.filename:
            return jsonify({'error': 'Files must have valid names'}), 400
        
        # Parse JSON files
        try:
            composition_data = json.loads(composition_file.read().decode('utf-8'))
            mapping_data = json.loads(mapping_file.read().decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return jsonify({
                'error': 'Invalid JSON in uploaded files',
                'details': str(e)
            }), 400
        
        # Parse demographics if provided
        demographics_data = None
        if demographics_file and demographics_file.filename:
            try:
                demographics_data = json.loads(demographics_file.read().decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return jsonify({
                    'error': 'Invalid JSON in demographics file',
                    'details': str(e)
                }), 400
        
        # Create transformer and perform transformation
        try:
            transformer = OpenEHRToFHIRTransformer(mapping_data)
            
            # Load composition
            composition = transformer.load_composition(composition_data)
            if not transformer.validate_composition(composition):
                return jsonify({
                    'error': 'Composition failed validation',
                    'details': transformer.validation_messages
                }), 400
            
            # Transform to FHIR resources
            include_pdf = request.form.get('include_pdf', '').lower() in {'1', 'true', 'yes', 'on'}
            resources = transformer.map_composition_to_resources(
                composition,
                demographics_data,
                include_pdf=include_pdf,
            )
            
            # Build bundle
            bundle = transformer.build_bundle(resources)
            
            return jsonify({
                'success': True,
                'bundle': bundle,
                'resource_count': len(resources)
            }), 200
        
        except ValueError as e:
            return jsonify({
                'error': 'Transformation error',
                'details': str(e)
            }), 400
        except Exception as e:
            logger.exception('Transformation failed')
            return jsonify({
                'error': 'Internal transformation error',
                'details': str(e)
            }), 500
    
    except Exception as e:
        logger.exception('Request processing failed')
        return jsonify({
            'error': 'Request processing error',
            'details': str(e)
        }), 500


@app.route('/transform/json', methods=['POST'])
def transform_json():
    """
    Transform openEHR composition to FHIR Bundle using JSON request body.
    
    Accepts JSON body:
    {
        "composition": { openEHR composition object },
        "mapping": { mapping configuration object },
        "demographics": { patient demographics object } (optional)
    }
    
    Returns:
    - JSON response containing FHIR Bundle or error details
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Request body must be valid JSON'}), 400
        
        # Validate required fields
        if 'composition' not in data or 'mapping' not in data:
            return jsonify({
                'error': 'Missing required fields',
                'required': ['composition', 'mapping'],
                'optional': ['demographics']
            }), 400
        
        composition_data = data['composition']
        mapping_data = data['mapping']
        demographics_data = data.get('demographics')
        include_pdf = bool(data.get('include_pdf', False))
        
        # Validate composition and mapping are objects
        if not isinstance(composition_data, dict):
            return jsonify({'error': 'Composition must be a JSON object'}), 400
        if not isinstance(mapping_data, dict):
            return jsonify({'error': 'Mapping must be a JSON object'}), 400
        
        # Create transformer and perform transformation
        try:
            transformer = OpenEHRToFHIRTransformer(mapping_data)
            
            # Load composition
            composition = transformer.load_composition(composition_data)
            if not transformer.validate_composition(composition):
                return jsonify({
                    'error': 'Composition failed validation',
                    'details': transformer.validation_messages
                }), 400
            
            # Transform to FHIR resources
            resources = transformer.map_composition_to_resources(
                composition,
                demographics_data,
                include_pdf=include_pdf,
            )
            
            # Build bundle
            bundle = transformer.build_bundle(resources)
            
            return jsonify({
                'success': True,
                'bundle': bundle,
                'resource_count': len(resources)
            }), 200
        
        except ValueError as e:
            return jsonify({
                'error': 'Transformation error',
                'details': str(e)
            }), 400
        except Exception as e:
            logger.exception('Transformation failed')
            return jsonify({
                'error': 'Internal transformation error',
                'details': str(e)
            }), 500
    
    except Exception as e:
        logger.exception('Request processing failed')
        return jsonify({
            'error': 'Request processing error',
            'details': str(e)
        }), 500


@app.route('/api/docs', methods=['GET'])
def api_docs():
    """API documentation endpoint."""
    docs = {
        'service': 'openEHR to FHIR Transformation API',
        'version': '1.0',
        'endpoints': [
            {
                'path': '/health',
                'method': 'GET',
                'description': 'Health check endpoint',
                'response': {'status': 'healthy', 'service': 'openEHR-to-FHIR-API'}
            },
            {
                'path': '/transform',
                'method': 'POST',
                'description': 'Transform openEHR composition to FHIR Bundle using file upload',
                'content_type': 'multipart/form-data',
                'parameters': {
                    'composition': {'type': 'file', 'required': True, 'description': 'openEHR composition JSON'},
                    'mapping': {'type': 'file', 'required': True, 'description': 'Mapping configuration JSON'},
                    'demographics': {'type': 'file', 'required': False, 'description': 'Patient demographics JSON'}
                },
                'response': {
                    'success': True,
                    'bundle': 'FHIR Bundle object',
                    'resource_count': 'Number of resources in bundle'
                }
            },
            {
                'path': '/transform/json',
                'method': 'POST',
                'description': 'Transform openEHR composition to FHIR Bundle using JSON body',
                'content_type': 'application/json',
                'parameters': {
                    'composition': {'type': 'object', 'required': True, 'description': 'openEHR composition object'},
                    'mapping': {'type': 'object', 'required': True, 'description': 'Mapping configuration object'},
                    'demographics': {'type': 'object', 'required': False, 'description': 'Patient demographics object'}
                },
                'response': {
                    'success': True,
                    'bundle': 'FHIR Bundle object',
                    'resource_count': 'Number of resources in bundle'
                }
            },
            {
                'path': '/api/docs',
                'method': 'GET',
                'description': 'API documentation'
            }
        ],
        'example_curl_file_upload': (
            'curl -X POST http://localhost:5000/transform '
            '-F "composition=@composition.json" '
            '-F "mapping=@mapping.json" '
            '-F "demographics=@person.json"'
        ),
        'example_curl_json_body': (
            'curl -X POST http://localhost:5000/transform/json '
            '-H "Content-Type: application/json" '
            '-d @payload.json'
        )
    }
    return jsonify(docs), 200


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file size limit exceeded."""
    return jsonify({
        'error': 'File too large',
        'details': 'Maximum file size is 50MB'
    }), 413


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({
        'error': 'Endpoint not found',
        'available_endpoints': ['/health', '/transform', '/transform/json', '/api/docs']
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({
        'error': 'Internal server error',
        'details': 'An unexpected error occurred'
    }), 500


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True
    )
