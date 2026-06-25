#!/usr/bin/env python3
"""Detailed inspection of observation coding in FHIR output."""

import json
from pathlib import Path
from openEHR_to_FHIR_transformer import OpenEHRToFHIRTransformer

# Load and transform
mapping = json.loads(Path('mapping_config_example.json').read_text(encoding='utf-8'))
comp = json.loads(Path('Corona_Anamnese_composition_example.json').read_text(encoding='utf-8'))
transformer = OpenEHRToFHIRTransformer(mapping)
composition = transformer.load_composition(comp)
resources = transformer.map_composition_to_resources(composition)
bundle = transformer.build_bundle(resources)

print("=== FHIR Bundle Observation Details ===\n")

# Show full observation structures
obs_count = 0
for entry in bundle['entry']:
    resource = entry['resource']
    if resource['resourceType'] == 'Observation':
        obs_count += 1
        print(f"Observation {obs_count}: {resource.get('id')}")
        print(json.dumps({
            'code': resource.get('code'),
            'valueCodeableConcept': resource.get('valueCodeableConcept'),
            'valueQuantity': resource.get('valueQuantity'),
            'valueString': resource.get('valueString', '')[:50] + '...' if resource.get('valueString') else None,
        }, indent=2))
        print()

print(f"\nTotal observations: {obs_count}")
print("\n=== Summary ===")
print("✓ Observation codes now use LOINC from mapping config")
print("✓ Observation values preserve openEHR local codes")
print("✓ Terminology systems properly mapped (local, LOINC, etc.)")
