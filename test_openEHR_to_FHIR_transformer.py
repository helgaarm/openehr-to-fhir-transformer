import json
import base64
import unittest
from unittest.mock import patch

from fhir_api import app
from openEHR_to_FHIR_transformer import OpenEHRToFHIRTransformer, load_mapping_config


class TestOpenEHRToFHIRTransformer(unittest.TestCase):
    def setUp(self):
        self.mapping_config = load_mapping_config('mapping_config_example.json')
        self.transformer = OpenEHRToFHIRTransformer(self.mapping_config)
        self.composition = self.transformer.load_composition('Corona_Anamnese_composition_example.json')

    def test_validate_composition_uses_template_and_opt_metadata(self):
        self.assertTrue(
            self.transformer.validate_composition(
                self.composition,
                composition_source='Corona_Anamnese_composition_example.json',
            ),
            self.transformer.validation_messages,
        )

    def test_map_composition_to_resources_includes_patient_and_encounter(self):
        resources = self.transformer.map_composition_to_resources(self.composition)
        self.assertGreaterEqual(len(resources), 7)
        self.assertEqual(resources[0]['resourceType'], 'Patient')
        self.assertEqual(resources[1]['resourceType'], 'Encounter')
        self.assertTrue(resources[1]['subject']['reference'].startswith('Patient/'))
        self.assertIn('reason', resources[1])
        reason_texts = [r['value'][0]['concept']['text'] for r in resources[1]['reason']]
        self.assertTrue(any('Symptoms' in t or 'Exposure' in t for t in reason_texts))

    def test_path_based_mapping_preserves_observation_components(self):
        resources = self.transformer.map_composition_to_resources(self.composition)
        observations = {resource['code']['coding'][0]['code']: resource for resource in resources[2:]}

        symptom = observations['54899-0']
        self.assertEqual(symptom['valueString'], 'Dry Cough')
        self.assertEqual(symptom['component'][0]['valueCodeableConcept']['text'], 'Present')

        travel = observations['94651-7']
        self.assertEqual(travel['valueCodeableConcept']['text'], 'Ja')
        self.assertEqual(
            travel['component'][0]['valueString'],
            'Visit to a family member in Montevideo, Uruguay',
        )

        body_temperature = observations['8310-5']
        self.assertEqual(body_temperature['code']['text'], 'Körpertemperatur')
        self.assertEqual(body_temperature['valueQuantity']['unit'], '°C')
        self.assertEqual(body_temperature['valueQuantity']['code'], 'Cel')

    def test_include_pdf_adds_document_reference_with_pdf_attachment(self):
        resources = self.transformer.map_composition_to_resources(
            self.composition,
            include_pdf=True,
        )

        document_reference = resources[-1]
        self.assertEqual(document_reference['resourceType'], 'DocumentReference')
        self.assertEqual(document_reference['status'], 'current')
        self.assertEqual(document_reference['subject']['reference'], f"Patient/{resources[0]['id']}")

        attachment = document_reference['content'][0]['attachment']
        self.assertEqual(attachment['contentType'], 'application/pdf')
        pdf_bytes = base64.b64decode(attachment['data'])
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        self.assertIn(b'%%EOF', pdf_bytes)

    def test_map_composition_to_resources_accepts_demographics_dict(self):
        with open('person.json', encoding='utf-8') as f:
            demographics = json.load(f)

        resources = self.transformer.map_composition_to_resources(
            self.composition,
            patient_demographics=demographics,
        )

        self.assertEqual(resources[0]['resourceType'], 'Patient')
        self.assertEqual(resources[0]['name'][0]['text'], 'Ritika')
        self.assertEqual(resources[1]['subject']['reference'], f"Patient/{resources[0]['id']}")

    def test_build_bundle_outputs_valid_json_strings(self):
        resources = self.transformer.map_composition_to_resources(self.composition)
        bundle = self.transformer.build_bundle(resources)
        bundle_json = json.dumps(bundle, ensure_ascii=False)
        self.assertIn('"resourceType": "Bundle"', bundle_json)
        self.assertIn('"effectiveDateTime": "2024-06-25T10:00:00+00:00"', bundle_json)

    @patch('openEHR_to_FHIR_transformer.requests')
    def test_send_bundle_uses_requests_post(self, mock_requests):
        mock_response = mock_requests.post.return_value
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {'success': True}

        resources = self.transformer.map_composition_to_resources(self.composition)
        bundle = self.transformer.build_bundle(resources)
        result = self.transformer.send_bundle(bundle, 'https://example.com/fhir')

        mock_requests.post.assert_called_once()
        self.assertEqual(result, {'success': True})

    def test_api_response_preserves_unicode_text(self):
        with open('Corona_Anamnese_composition_example.json', encoding='utf-8') as f:
            composition = json.load(f)
        with open('mapping_config_example.json', encoding='utf-8') as f:
            mapping = json.load(f)

        response = app.test_client().post(
            '/transform/json',
            json={'composition': composition, 'mapping': mapping, 'include_pdf': True},
        )

        self.assertEqual(response.status_code, 200)
        bundle = response.get_json()['bundle']
        self.assertEqual(bundle['entry'][-1]['resource']['resourceType'], 'DocumentReference')
        response_text = response.get_data(as_text=True)
        self.assertIn('Körpertemperatur', response_text)
        self.assertNotIn('K\\u00f6rpertemperatur', response_text)

    def test_home_page_exposes_pdf_option(self):
        response = app.test_client().get('/')

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="include_pdf"', html)
        self.assertIn('DocumentReference', html)


if __name__ == '__main__':
    unittest.main()
