#!/usr/bin/env python3
"""Inspect coding data in openEHR composition and FHIR output."""

import json
from pathlib import Path

def find_coded_text(obj, path='', depth=0):
    """Recursively find all DV_CODED_TEXT entries."""
    if depth > 20:  # Prevent infinite recursion
        return
    
    if isinstance(obj, dict):
        if obj.get('@xsi:type') == 'DV_CODED_TEXT':
            print(f'{path}:')
            print(f'  value: {obj.get("value")}')
            if 'defining_code' in obj:
                code = obj['defining_code']
                print(f'  code: {code.get("code_string")}')
                print(f'  terminology: {code.get("terminology_id", {}).get("value")}')
            print()
        for k, v in obj.items():
            find_coded_text(v, f'{path}.{k}' if path else k, depth+1)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            find_coded_text(item, f'{path}[{i}]', depth+1)

print("=== OpenEHR Coded Text Values ===\n")
comp = json.loads(Path('Corona_Anamnese_composition_example.json').read_text(encoding='utf-8'))
find_coded_text(comp)

print("\n\n=== FHIR Bundle Observation Codes ===\n")
# Transform and check the output
from openEHR_to_FHIR_transformer import OpenEHRToFHIRTransformer

mapping = json.loads(Path('mapping_config_example.json').read_text(encoding='utf-8'))
transformer = OpenEHRToFHIRTransformer(mapping)
composition = transformer.load_composition(comp)
resources = transformer.map_composition_to_resources(composition)
bundle = transformer.build_bundle(resources)

# Show observation codes and values
for entry in bundle['entry']:
    resource = entry['resource']
    if resource['resourceType'] == 'Observation':
        print(f"Observation: {resource.get('code', {}).get('text', 'N/A')}")
        if 'coding' in resource.get('code', {}):
            for coding in resource['code']['coding']:
                print(f"  system: {coding.get('system')}")
                print(f"  code: {coding.get('code')}")
                print(f"  display: {coding.get('display')}")
        print(f"  value type: {type(resource.get('value')).__name__ if resource.get('value') else 'None'}")
        if 'valueCodeableConcept' in resource:
            print(f"  valueCodeableConcept: {json.dumps(resource['valueCodeableConcept'], indent=4)}")
        print()
