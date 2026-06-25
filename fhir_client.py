#!/usr/bin/env python3
"""
Python client for the openEHR to FHIR Transformation API.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests


class FHIRTransformationClient:
    """Client for interacting with the openEHR to FHIR Transformation API."""

    def __init__(self, base_url: str = 'http://localhost:5000'):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()

    def health_check(self) -> Dict[str, Any]:
        response = self.session.get(f'{self.base_url}/health')
        response.raise_for_status()
        return response.json()

    def transform_files(
        self,
        composition_path: Union[str, Path],
        mapping_path: Union[str, Path],
        demographics_path: Optional[Union[str, Path]] = None,
        include_pdf: bool = False,
    ) -> Dict[str, Any]:
        files = {}

        comp_path = Path(composition_path)
        if not comp_path.exists():
            raise FileNotFoundError(f'Composition file not found: {comp_path}')
        files['composition'] = open(comp_path, 'rb')

        map_path = Path(mapping_path)
        if not map_path.exists():
            raise FileNotFoundError(f'Mapping file not found: {map_path}')
        files['mapping'] = open(map_path, 'rb')

        if demographics_path:
            demo_path = Path(demographics_path)
            if not demo_path.exists():
                raise FileNotFoundError(f'Demographics file not found: {demo_path}')
            files['demographics'] = open(demo_path, 'rb')

        try:
            data = {'include_pdf': 'true'} if include_pdf else None
            response = self.session.post(f'{self.base_url}/transform', files=files, data=data)
            response.raise_for_status()
            return response.json()
        finally:
            for file in files.values():
                file.close()

    def transform_json(
        self,
        composition: Dict[str, Any],
        mapping: Dict[str, Any],
        demographics: Optional[Dict[str, Any]] = None,
        include_pdf: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            'composition': composition,
            'mapping': mapping,
        }

        if demographics:
            payload['demographics'] = demographics
        if include_pdf:
            payload['include_pdf'] = True

        response = self.session.post(f'{self.base_url}/transform/json', json=payload)
        response.raise_for_status()
        return response.json()

    def get_api_docs(self) -> Dict[str, Any]:
        response = self.session.get(f'{self.base_url}/api/docs')
        response.raise_for_status()
        return response.json()

    def transform_and_save(
        self,
        composition_path: Union[str, Path],
        mapping_path: Union[str, Path],
        output_path: Union[str, Path],
        demographics_path: Optional[Union[str, Path]] = None,
        include_pdf: bool = False,
    ) -> None:
        result = self.transform_files(
            composition_path,
            mapping_path,
            demographics_path,
            include_pdf=include_pdf,
        )

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result['bundle'], f, indent=2, ensure_ascii=False)

        print(f'Bundle saved to {output_path}')
        print(f'Resources created: {result["resource_count"]}')


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 4:
        print('Usage: python fhir_client.py <composition.json> <mapping.json> <output.json> [demographics.json] [--include-pdf]')
        print('\nExample:')
        print('  python fhir_client.py Corona_Anamnese_composition_example.json mapping_config_example.json output_bundle.json person.json --include-pdf')
        sys.exit(1)

    include_pdf = '--include-pdf' in sys.argv
    args = [arg for arg in sys.argv[1:] if arg != '--include-pdf']

    composition_file = args[0]
    mapping_file = args[1]
    output_file = args[2]
    demographics_file = args[3] if len(args) > 3 else None

    try:
        client = FHIRTransformationClient()
        print('Checking API health...')
        health = client.health_check()
        print(f'API is healthy: {health["service"]}')

        print('\nTransforming files...')
        client.transform_and_save(
            composition_file,
            mapping_file,
            output_file,
            demographics_file,
            include_pdf=include_pdf,
        )
    except Exception as e:
        print(f'Error: {e}')
        sys.exit(1)
