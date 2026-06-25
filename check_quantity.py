#!/usr/bin/env python3
"""Check quantity representation in FHIR output."""

import json
from pathlib import Path
from openEHR_to_FHIR_transformer import OpenEHRToFHIRTransformer

mapping = json.loads(Path('mapping_config_example.json').read_text(encoding='utf-8'))
comp = json.loads(Path('Corona_Anamnese_composition_example.json').read_text(encoding='utf-8'))
transformer = OpenEHRToFHIRTransformer(mapping)
composition = transformer.load_composition(comp)
resources = transformer.map_composition_to_resources(composition)
bundle = transformer.build_bundle(resources)

print("=== All Observations with Quantities ===\n")
found = False
for entry in bundle['entry']:
    resource = entry['resource']
    if resource['resourceType'] == 'Observation':
        qty = resource.get('valueQuantity')
        if qty:
            found = True
            print(f"Observation: {resource.get('code', {}).get('text', 'N/A')}")
            print(f"ID: {resource.get('id')}")
            print(f"Quantity:")
            print(json.dumps(qty, indent=2, ensure_ascii=False))
            print()

if not found:
    print("No observations with valueQuantity found")
    print("\nAvailable observations:")
    for entry in bundle['entry']:
        resource = entry['resource']
        if resource['resourceType'] == 'Observation':
            print(f"  - {resource.get('code', {}).get('text', 'N/A')}")
            if 'valueString' in resource:
                print(f"    (has valueString)")
            if 'valueCodeableConcept' in resource:
                print(f"    (has valueCodeableConcept)")
            if 'valueQuantity' in resource:
                print(f"    (has valueQuantity)")
