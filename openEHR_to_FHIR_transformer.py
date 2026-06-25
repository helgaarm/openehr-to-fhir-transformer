import argparse
import base64
import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Union

from fhir.resources.bundle import Bundle
from fhir.resources.documentreference import DocumentReference
from fhir.resources.encounter import Encounter
from fhir.resources.medicationrequest import MedicationRequest
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient

from openEHR_model import (
    Composition,
    ContentItem,
    Section,
    DVQuantity,
    DVCodedText,
    DVText,
    ItemTree,
    Element,
    FlattenedValue,
    flatten_item_tree,
)
from pdf_document import build_text_pdf

try:
    import requests
except ImportError:
    requests = None


class OpenEHRToFHIRTransformer:
    def __init__(self, mapping_config: Dict[str, Any]) -> None:
        self.mapping_config = mapping_config
        self.patient_reference: str = 'Patient/example'
        self.validation_messages: List[str] = []
        self.resource_id_counts: Dict[str, int] = {}

    def load_composition(self, path_or_dict: Union[str, Dict[str, Any]]) -> Composition:
        """Load composition from file path or dictionary."""
        if isinstance(path_or_dict, dict):
            composition_json = path_or_dict
        else:
            with open(path_or_dict, 'r', encoding='utf-8') as f:
                composition_json = json.load(f)
        return Composition.from_dict(composition_json)

    def validate_composition(
        self,
        composition: Composition,
        composition_source: Optional[str] = None,
    ) -> bool:
        self.validation_messages = []

        if not composition.data.content:
            self.validation_messages.append('Composition has no content items.')

        template_config = self.mapping_config.get('template', {})
        expected_template_id = template_config.get('template_id') or self.mapping_config.get('template_id')
        if expected_template_id and composition.template_id != expected_template_id:
            self.validation_messages.append(
                f'Composition template_id {composition.template_id!r} does not match expected '
                f'{expected_template_id!r}.'
            )

        opt_path = template_config.get('opt_path') or self.mapping_config.get('opt_path')
        if opt_path and not self._validate_against_opt_file(composition, opt_path):
            self.validation_messages.append(f'OPT validation failed for {opt_path!r}.')

        validator_command = template_config.get('java_validator_command')
        if validator_command:
            if not composition_source:
                self.validation_messages.append(
                    'java_validator_command is configured, but no composition file path was provided.'
                )
            elif not self._run_java_sdk_validator(validator_command, composition_source):
                self.validation_messages.append('External openEHR SDK validator failed.')

        return not self.validation_messages

    def map_composition_to_resources(
        self,
        composition: Composition,
        patient_demographics: Optional[Union[str, Dict[str, Any]]] = None,
        include_pdf: bool = False,
    ) -> List[Dict[str, Any]]:
        resources: List[Dict[str, Any]] = []
        self.resource_id_counts = {}

        patient = self._map_patient(composition, patient_demographics)
        if patient:
            resources.append(patient)
            self.patient_reference = f"Patient/{patient['id']}"

        encounter = self._map_encounter(composition, self.patient_reference)
        if encounter:
            resources.append(encounter)

        for item in composition.data.content:
            resources.extend(self._map_content_item_recursive(item))

        if include_pdf:
            document_reference = self._map_pdf_document_reference(composition)
            resources.append(document_reference)

        return resources

    def _map_content_item_recursive(self, item: ContentItem) -> List[Dict[str, Any]]:
        resources: List[Dict[str, Any]] = []
        resource = self._map_composition_item(item)
        if resource:
            resources.append(resource)

        for child in item.items:
            resources.extend(self._map_content_item_recursive(child))

        return resources

    def _map_composition_item(self, item: ContentItem) -> Optional[Dict[str, Any]]:
        mapping = self._find_mapping(item.archetype_node_id)
        if not mapping:
            return None

        resource_type = mapping['resource_type']
        profile = mapping.get('fhir_profile')

        if resource_type == 'Observation':
            return self._map_observation(item, mapping)
        if resource_type == 'MedicationRequest':
            return self._map_medication_request(item, mapping)

        resource = {
            'resourceType': resource_type,
            'id': self._make_resource_id(item),
        }
        if profile:
            resource['meta'] = {'profile': [profile]}
        return resource

    def _find_mapping(self, archetype_id: Optional[str]) -> Optional[Dict[str, Any]]:
        for entry in self.mapping_config.get('mappings', []):
            if entry.get('archetype_id') == archetype_id:
                return entry
        return None

    def _make_resource_id(self, item: ContentItem) -> str:
        uid = item.archetype_node_id or 'unknown'
        return self._make_unique_resource_id(self._normalize_resource_id(uid))

    def _make_resource_id_from_string(self, source: str) -> str:
        return self._normalize_resource_id(source)

    def _normalize_resource_id(self, source: str) -> str:
        normalized = source.replace('openEHR-EHR-', '').replace('.', '-').replace('_', '-').lower()
        normalized = ''.join(ch for ch in normalized if ch.isalnum() or ch in '-.')
        return normalized[:64] or 'resource-1'

    def _make_unique_resource_id(self, base_id: str) -> str:
        count = self.resource_id_counts.get(base_id, 0) + 1
        self.resource_id_counts[base_id] = count
        if count == 1:
            return base_id

        suffix = f'-{count}'
        return f'{base_id[:64 - len(suffix)]}{suffix}'

    def _map_patient(
        self,
        composition: Composition,
        patient_demographics: Optional[Union[str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        if patient_demographics:
            patient = self._load_patient_from_demographics(patient_demographics)
            if patient:
                return patient

        patient_id = f"patient-{self._make_resource_id_from_string(composition.uid or 'example')}"
        patient_data: Dict[str, Any] = {
            'id': patient_id,
            'name': [{'text': 'Patient'}],
            'gender': 'unknown',
        }
        profile = self.mapping_config.get(
            'patient_profile', 'http://hl7.org/fhir/StructureDefinition/Patient'
        )
        if profile:
            patient_data['meta'] = {'profile': [profile]}

        patient = Patient(**patient_data)
        return patient.dict(by_alias=True, exclude_none=True)

    def _load_patient_from_demographics(
        self,
        demographics: Union[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if isinstance(demographics, dict):
            person_data = demographics
        else:
            try:
                with open(demographics, 'r', encoding='utf-8') as f:
                    person_data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return None

        archetype_id = None
        if isinstance(person_data.get('archetype_node_id'), str):
            archetype_id = person_data.get('archetype_node_id')
        elif isinstance(person_data.get('archetype_details'), dict):
            archetype_id = person_data['archetype_details'].get('archetype_id', {}).get('value')

        if not archetype_id or 'DEMOGRAPHIC-PERSON' not in archetype_id:
            return None

        uid_value = None
        if isinstance(person_data.get('uid'), dict):
            uid_value = person_data['uid'].get('value')
        elif isinstance(person_data.get('uid'), str):
            uid_value = person_data['uid']

        patient_id = f"patient-{self._make_resource_id_from_string(uid_value or 'example')}"
        names = []
        def add_text(value: Any) -> None:
            if isinstance(value, str) and value.strip():
                names.append({'text': value.strip()})
            elif isinstance(value, dict):
                inner = value.get('value') or value.get('text')
                if isinstance(inner, str) and inner.strip():
                    names.append({'text': inner.strip()})

        for entry in person_data.get('content', []):
            if not isinstance(entry, dict):
                continue
            add_text(entry.get('name'))
            add_text(entry.get('value'))

        if isinstance(person_data.get('name'), str):
            add_text(person_data.get('name'))
        elif isinstance(person_data.get('name'), dict):
            add_text(person_data.get('name'))

        if not names:
            names = [{'text': 'Patient'}]

        patient_data: Dict[str, Any] = {'id': patient_id, 'name': names}
        gender = person_data.get('gender')
        if isinstance(gender, str):
            patient_data['gender'] = gender

        birth_date = person_data.get('date_of_birth') or person_data.get('birthDate')
        if isinstance(birth_date, str):
            patient_data['birthDate'] = birth_date

        profile = self.mapping_config.get(
            'patient_profile', 'http://hl7.org/fhir/StructureDefinition/Patient'
        )
        if profile:
            patient_data['meta'] = {'profile': [profile]}

        patient = Patient(**patient_data)
        return patient.dict(by_alias=True, exclude_none=True)

    def _map_encounter(
        self,
        composition: Composition,
        patient_reference: str,
    ) -> Dict[str, Any]:
        encounter_id = f"encounter-{self._make_resource_id_from_string(composition.uid or 'example')}"
        encounter_data: Dict[str, Any] = {
            'id': encounter_id,
            'status': 'finished',
            'class_fhir': [
                {
                    'coding': [
                        {
                            'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode',
                            'code': 'AMB',
                            'display': 'ambulatory',
                        }
                    ]
                }
            ],
            'subject': {'reference': patient_reference},
        }

        if self.mapping_config.get('encounter_profile'):
            encounter_data['meta'] = {'profile': [self.mapping_config['encounter_profile']]}

        start_time = self._extract_composition_start_time(composition)
        if start_time:
            encounter_data['actualPeriod'] = {'start': start_time}

        setting = self._extract_composition_setting(composition)
        if setting:
            encounter_data['class_fhir'] = [
                {
                    'coding': [
                        {
                            'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode',
                            'code': 'HH' if setting.lower() == 'home' else 'AMB',
                            'display': setting,
                        }
                    ]
                }
            ]

        reasons = self._extract_encounter_reasons(composition)
        if reasons:
            encounter_data['reason'] = reasons

        encounter = Encounter(**encounter_data)
        return encounter.dict(by_alias=True, exclude_none=True)

    def _extract_composition_start_time(self, composition: Composition) -> Optional[str]:
        if composition.context and isinstance(composition.context, dict):
            start_time = composition.context.get('start_time')
            if isinstance(start_time, dict):
                return self._normalize_openEHR_datetime(start_time.get('value', ''))
        return None

    def _extract_composition_setting(self, composition: Composition) -> Optional[str]:
        if composition.context and isinstance(composition.context, dict):
            setting = composition.context.get('setting')
            if isinstance(setting, dict):
                return setting.get('value')
        return None

    def _extract_encounter_reasons(self, composition: Composition) -> Optional[List[Dict[str, Any]]]:
        reasons: List[Dict[str, Any]] = []
        for item in composition.data.content:
            if isinstance(item, Section) and item.name:
                reasons.append({'value': [{'concept': {'text': item.name}}]})
        return reasons if reasons else None

    def _map_pdf_document_reference(self, composition: Composition) -> Dict[str, Any]:
        source_id = self._make_resource_id_from_string(composition.uid or 'example')
        document_id = f"docref-{source_id}"[:64]
        title = f"{composition.template_id or 'openEHR'} Composition Summary"
        pdf_bytes = build_text_pdf(title, self._composition_summary_lines(composition))
        pdf_base64 = base64.b64encode(pdf_bytes).decode('ascii')

        document_reference_data: Dict[str, Any] = {
            'id': document_id,
            'status': 'current',
            'docStatus': 'final',
            'subject': {'reference': self.patient_reference},
            'type': {
                'coding': [
                    {
                        'system': 'http://loinc.org',
                        'code': '34133-9',
                        'display': 'Summary of episode note',
                    }
                ],
                'text': title,
            },
            'description': 'PDF summary generated from the source openEHR composition.',
            'content': [
                {
                    'attachment': {
                        'contentType': 'application/pdf',
                        'data': pdf_base64,
                        'title': f'{title}.pdf',
                    }
                }
            ],
        }

        start_time = self._extract_composition_start_time(composition)
        if start_time:
            document_reference_data['date'] = start_time

        document_reference = DocumentReference(**document_reference_data)
        return document_reference.dict(by_alias=True, exclude_none=True)

    def _composition_summary_lines(self, composition: Composition) -> List[str]:
        lines = [
            f'Composition UID: {composition.uid or "unknown"}',
            f'Template ID: {composition.template_id or "unknown"}',
        ]

        start_time = self._extract_composition_start_time(composition)
        if start_time:
            lines.append(f'Start time: {start_time}')

        setting = self._extract_composition_setting(composition)
        if setting:
            lines.append(f'Setting: {setting}')

        lines.append('')
        lines.append('Clinical content')

        for item in self._iter_content_items(composition.data.content):
            if isinstance(item, Section):
                lines.append('')
                lines.append(f'[{item.name}]')
                continue
            if item.xsi_type == 'ACTIVITY':
                continue

            flattened_values = self._summary_values_for_item(item)
            if not flattened_values:
                continue

            item_type = item.xsi_type or 'CONTENT'
            lines.append('')
            lines.append(f'{item.name or item.archetype_node_id} ({item_type}):')
            if not flattened_values:
                lines.append('  No values found')
                continue
            for flattened_value in flattened_values:
                if flattened_value.path == '/data/events/time':
                    continue
                lines.append(
                    f'  - {flattened_value.name or flattened_value.archetype_node_id}: '
                    f'{self._summary_value_text(flattened_value.value)}'
                )

        return lines

    def _summary_values_for_item(self, item: ContentItem) -> List[FlattenedValue]:
        if item.xsi_type == 'OBSERVATION':
            return self._flatten_content_item_values(item)
        if item.xsi_type == 'INSTRUCTION':
            return self._flatten_instruction_values(item)

        flattened_values: List[FlattenedValue] = []
        if item.protocol:
            flattened_values.extend(
                flatten_item_tree(item.protocol, f'/protocol[{item.protocol.archetype_node_id}]')
            )
        if item.description:
            flattened_values.extend(
                flatten_item_tree(item.description, f'/description[{item.description.archetype_node_id}]')
            )
        return flattened_values

    def _iter_content_items(self, items: List[ContentItem]) -> List[ContentItem]:
        flattened: List[ContentItem] = []
        for item in items:
            flattened.append(item)
            flattened.extend(self._iter_content_items(item.items))
        return flattened

    def _summary_value_text(self, value: Any) -> str:
        fhir_value = self._value_to_fhir(value)
        if isinstance(fhir_value, dict):
            if 'text' in fhir_value:
                return str(fhir_value['text'])
            if 'value' in fhir_value and 'unit' in fhir_value:
                return f"{fhir_value['value']} {fhir_value['unit']}"
            return json.dumps(fhir_value, ensure_ascii=False)
        return str(fhir_value)

    def _map_observation(self, item: ContentItem, mapping: Dict[str, Any]) -> Dict[str, Any]:
        profile = mapping.get('fhir_profile')
        fields = mapping.get('fields', {})
        flattened_values = self._flatten_content_item_values(item)
        effective = self._extract_effective_time(item)
        code_data = self._extract_observation_code(item)

        observation_data: Dict[str, Any] = {
            'id': self._make_resource_id(item),
            'status': 'final',
            'code': code_data,
            'subject': {'reference': self.patient_reference},
        }

        if profile:
            observation_data['meta'] = {'profile': [profile]}

        effective_path = fields.get('effectiveDateTime')
        if effective_path:
            effective_value = self._get_flattened_value(flattened_values, effective_path)
            if effective_value:
                effective = self._normalize_openEHR_datetime(str(effective_value.value))

        if effective:
            observation_data['effectiveDateTime'] = effective

        mapped_value = self._extract_mapped_observation_value(fields, flattened_values)
        if mapped_value:
            field_name, value = mapped_value
            self._assign_observation_value(observation_data, field_name, value)
        else:
            value = self._extract_value(item)
            if value is not None:
                self._assign_observation_value(observation_data, None, value)

        components = self._map_observation_components(fields.get('components', []), flattened_values)
        if components:
            observation_data['component'] = components

        if not any(key.startswith('value') for key in observation_data) and not components:
            observation_data['dataAbsentReason'] = {'text': 'No mapped openEHR value found'}

        observation = Observation(**observation_data)
        return observation.dict(by_alias=True, exclude_none=True)

    def _map_medication_request(self, item: ContentItem, mapping: Dict[str, Any]) -> Dict[str, Any]:
        profile = mapping.get('fhir_profile')
        fields = mapping.get('fields', {})
        flattened_values = self._flatten_instruction_values(item)

        medication_text = self._text_from_path(flattened_values, fields.get('medication')) or item.name
        medication_request_data: Dict[str, Any] = {
            'id': self._make_resource_id(item),
            'status': self._medication_request_status(
                self._text_from_path(flattened_values, fields.get('status'))
            ),
            'intent': mapping.get('intent', 'order'),
            'medication': {'concept': {'text': medication_text}},
            'subject': {'reference': self.patient_reference},
        }

        if profile:
            medication_request_data['meta'] = {'profile': [profile]}

        authored_on = self._fhir_datetime_from_path(flattened_values, fields.get('authoredOn'))
        if authored_on:
            medication_request_data['authoredOn'] = authored_on

        reason_text = self._text_from_path(flattened_values, fields.get('reason'))
        if reason_text:
            medication_request_data['reason'] = [{'concept': {'text': reason_text}}]

        dosage_instruction = self._map_dosage_instruction(fields, flattened_values)
        if dosage_instruction:
            medication_request_data['dosageInstruction'] = [dosage_instruction]

        medication_request = MedicationRequest(**medication_request_data)
        return medication_request.dict(by_alias=True, exclude_none=True)

    def _map_dosage_instruction(
        self,
        fields: Dict[str, Any],
        flattened_values: List[FlattenedValue],
    ) -> Dict[str, Any]:
        dosage: Dict[str, Any] = {}

        dosage_text = self._text_from_path(flattened_values, fields.get('dosageText'))
        if dosage_text:
            dosage['text'] = dosage_text

        additional_instruction = self._text_from_path(flattened_values, fields.get('additionalInstruction'))
        if additional_instruction:
            dosage['patientInstruction'] = additional_instruction

        route = self._text_from_path(flattened_values, fields.get('route'))
        if route:
            dosage['route'] = {'text': route}

        dose_value = self._fhir_value_from_path(flattened_values, fields.get('doseQuantity'))
        if isinstance(dose_value, dict) and 'value' in dose_value:
            dosage['doseAndRate'] = [{'doseQuantity': dose_value}]

        return dosage

    def _extract_mapped_observation_value(
        self,
        fields: Dict[str, Any],
        flattened_values: List[FlattenedValue],
    ) -> Optional[tuple[str, Any]]:
        for field_name in ('valueQuantity', 'valueCodeableConcept', 'valueString'):
            path = fields.get(field_name)
            if not path:
                continue
            flattened_value = self._get_flattened_value(flattened_values, path)
            if flattened_value:
                return field_name, self._value_to_fhir(flattened_value.value)
        return None

    def _assign_observation_value(
        self,
        observation_data: Dict[str, Any],
        preferred_field: Optional[str],
        value: Any,
    ) -> None:
        if preferred_field == 'valueQuantity':
            observation_data['valueQuantity'] = value
            return
        if preferred_field == 'valueCodeableConcept':
            observation_data['valueCodeableConcept'] = value if isinstance(value, dict) else {'text': str(value)}
            return
        if preferred_field == 'valueString':
            observation_data['valueString'] = self._string_from_fhir_value(value)
            return

        if isinstance(value, dict):
            if 'value' in value and 'unit' in value:
                observation_data['valueQuantity'] = value
            elif 'coding' in value or 'code' in value:
                observation_data['valueCodeableConcept'] = value
            else:
                observation_data['valueString'] = json.dumps(value, ensure_ascii=False)
        else:
            observation_data['valueString'] = value

    def _map_observation_components(
        self,
        component_configs: List[Dict[str, Any]],
        flattened_values: List[FlattenedValue],
    ) -> List[Dict[str, Any]]:
        components: List[Dict[str, Any]] = []

        for component_config in component_configs:
            path = component_config.get('path')
            if not path:
                continue

            flattened_value = self._get_flattened_value(flattened_values, path)
            if not flattened_value:
                continue

            component: Dict[str, Any] = {
                'code': component_config.get('code') or {'text': flattened_value.name}
            }
            value = self._value_to_fhir(flattened_value.value)
            self._assign_component_value(component, component_config.get('value_field'), value)
            components.append(component)

        return components

    def _assign_component_value(
        self,
        component: Dict[str, Any],
        preferred_field: Optional[str],
        value: Any,
    ) -> None:
        if preferred_field == 'valueString':
            component['valueString'] = self._string_from_fhir_value(value)
        elif preferred_field == 'valueCodeableConcept':
            component['valueCodeableConcept'] = value if isinstance(value, dict) else {'text': str(value)}
        elif preferred_field == 'valueQuantity':
            component['valueQuantity'] = value
        elif isinstance(value, dict) and 'value' in value and 'unit' in value:
            component['valueQuantity'] = value
        elif isinstance(value, dict) and ('coding' in value or 'code' in value):
            component['valueCodeableConcept'] = value
        else:
            component['valueString'] = str(value)

    def _string_from_fhir_value(self, value: Any) -> str:
        if isinstance(value, dict):
            if isinstance(value.get('text'), str):
                return value['text']
            if 'value' in value and 'unit' in value:
                return f"{value['value']} {value['unit']}"
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _extract_observation_code(self, item: ContentItem) -> Dict[str, Any]:
        """Extract or derive FHIR coding for an observation from archetype mapping."""
        # Try to get coding from mapping
        if item.archetype_node_id:
            for mapping_entry in self.mapping_config.get('mappings', []):
                if mapping_entry.get('archetype_id') == item.archetype_node_id:
                    if 'coding' in mapping_entry:
                        coding = mapping_entry['coding']
                        return {
                            'coding': [{
                                'system': coding.get('system'),
                                'code': coding.get('code'),
                                'display': coding.get('display', item.name)
                            }],
                            'text': item.name
                        }
        
        # Fallback: Create coding from archetype identifier
        return {
            'coding': [self._archetype_to_coding(item.archetype_node_id)],
            'text': item.name
        } if item.archetype_node_id else {'text': item.name}

    def _archetype_to_coding(self, archetype_id: str) -> Dict[str, str]:
        """Convert openEHR archetype ID to a FHIR coding."""
        # Extract the meaningful part: openEHR-EHR-OBSERVATION.body_temperature.v2
        # -> use as code: body_temperature.v2
        # or just: body_temperature
        parts = archetype_id.split('.')
        if len(parts) >= 2:
            archetype_name = parts[1]
        else:
            archetype_name = archetype_id
        
        terminology_system = self.mapping_config.get(
            'terminology_system',
            'http://terminology.openehr.org/CodeSystem/openehr-archetypes'
        )
        
        return {
            'system': terminology_system,
            'code': archetype_name,
            'display': archetype_name.replace('_', ' ').title()
        }

    def _extract_effective_time(self, item: ContentItem) -> Optional[str]:
        raw_time = None
        if item.data and item.data.origin:
            raw_time = item.data.origin

        if raw_time is None and item.context and isinstance(item.context, dict):
            start_time = item.context.get('start_time')
            if isinstance(start_time, dict):
                raw_time = start_time.get('value')

        if raw_time is None:
            return None

        return self._normalize_openEHR_datetime(raw_time)

    def _flatten_content_item_values(self, item: ContentItem) -> List[FlattenedValue]:
        flattened_values: List[FlattenedValue] = []
        if not item.data or not item.data.events:
            return flattened_values

        if item.data.events.time:
            flattened_values.append(
                FlattenedValue(
                    path='/data/events/time',
                    archetype_node_id='time',
                    name='Event time',
                    value=item.data.events.time,
                    value_type='DV_DATE_TIME',
                )
            )

        if item.data.events.data:
            flattened_values.extend(flatten_item_tree(item.data.events.data, '/data/events/data'))

        return flattened_values

    def _flatten_instruction_values(self, item: ContentItem) -> List[FlattenedValue]:
        flattened_values: List[FlattenedValue] = []

        if item.protocol:
            protocol_base = f'/protocol[{item.protocol.archetype_node_id}]'
            flattened_values.extend(flatten_item_tree(item.protocol, protocol_base))

        if item.description:
            description_base = f'/description[{item.description.archetype_node_id}]'
            flattened_values.extend(flatten_item_tree(item.description, description_base))

        for activity in item.items:
            if activity.description:
                activity_id = activity.archetype_node_id or 'unknown'
                description_id = activity.description.archetype_node_id or 'unknown'
                description_base = f'/activities[{activity_id}]/description[{description_id}]'
                flattened_values.extend(flatten_item_tree(activity.description, description_base))
            if activity.protocol:
                activity_id = activity.archetype_node_id or 'unknown'
                protocol_id = activity.protocol.archetype_node_id or 'unknown'
                protocol_base = f'/activities[{activity_id}]/protocol[{protocol_id}]'
                flattened_values.extend(flatten_item_tree(activity.protocol, protocol_base))

        return flattened_values

    def _fhir_value_from_path(
        self,
        flattened_values: List[FlattenedValue],
        path: Optional[str],
    ) -> Optional[Any]:
        if not path:
            return None
        flattened_value = self._get_flattened_value(flattened_values, path)
        if not flattened_value:
            return None
        return self._value_to_fhir(flattened_value.value)

    def _text_from_path(
        self,
        flattened_values: List[FlattenedValue],
        path: Optional[str],
    ) -> Optional[str]:
        value = self._fhir_value_from_path(flattened_values, path)
        if value is None:
            return None
        return self._string_from_fhir_value(value)

    def _fhir_datetime_from_path(
        self,
        flattened_values: List[FlattenedValue],
        path: Optional[str],
    ) -> Optional[str]:
        raw_value = self._text_from_path(flattened_values, path)
        if not raw_value or '$' in raw_value:
            return None
        normalized = self._normalize_openEHR_datetime(raw_value)
        if normalized:
            return normalized
        if 'T' in raw_value and len(raw_value) >= 10:
            return raw_value
        return None

    def _medication_request_status(self, status_text: Optional[str]) -> str:
        if not status_text:
            return 'active'
        normalized = status_text.strip().lower()
        status_map = {
            'active': 'active',
            'on hold': 'on-hold',
            'on-hold': 'on-hold',
            'ended': 'ended',
            'stopped': 'stopped',
            'completed': 'completed',
            'cancelled': 'cancelled',
            'canceled': 'cancelled',
            'draft': 'draft',
            'entered in error': 'entered-in-error',
            'unknown': 'unknown',
        }
        return status_map.get(normalized, 'active')

    def _get_flattened_value(
        self,
        flattened_values: List[FlattenedValue],
        path: str,
    ) -> Optional[FlattenedValue]:
        normalized_path = self._normalize_mapping_path(path)
        for flattened_value in flattened_values:
            if self._normalize_mapping_path(flattened_value.path) == normalized_path:
                return flattened_value
        return None

    def _normalize_mapping_path(self, path: str) -> str:
        normalized = path.strip()
        if normalized.endswith('/value'):
            normalized = normalized[:-6]
        return normalized

    def _normalize_openEHR_datetime(self, raw_time: str) -> Optional[str]:
        # Convert openEHR timestamp format like 20240625T100000,000+0000 to strict ISO 8601
        try:
            if 'T' not in raw_time:
                return None

            date_part, rest = raw_time.split('T', 1)
            if len(date_part) != 8:
                return None

            year = date_part[0:4]
            month = date_part[4:6]
            day = date_part[6:8]

            tz_sign = '+' if '+' in rest else '-' if '-' in rest else None
            if tz_sign:
                time_part, tz_part = rest.split(tz_sign, 1)
                tz_part = tz_part.strip()
            else:
                time_part = rest
                tz_part = '00:00'

            if ',' in time_part:
                time_main, fraction = time_part.split(',', 1)
                time_main = time_main.zfill(6)
                fraction = fraction.rstrip('Z')
                fraction = fraction.split('Z')[0]
                time_main_formatted = f"{time_main[0:2]}:{time_main[2:4]}:{time_main[4:6]}"
                normalized_time = f"{time_main_formatted}.{fraction}"
            else:
                time_main = time_part.strip().zfill(6)
                normalized_time = f"{time_main[0:2]}:{time_main[2:4]}:{time_main[4:6]}"

            if tz_sign:
                tz_part = tz_part.replace(':', '')
                tz_part = tz_part.zfill(4)
                tz_formatted = f"{tz_sign}{tz_part[0:2]}:{tz_part[2:4]}"
            else:
                tz_formatted = '+00:00'

            if tz_formatted == '+00:00':
                tz_formatted = 'Z'

            return f"{year}-{month}-{day}T{normalized_time}{tz_formatted}"
        except Exception:
            return None

    def _extract_value(self, item: ContentItem) -> Optional[Any]:
        if not item.data or not item.data.events or not item.data.events.data:
            return None
        return self._extract_value_from_itemtree(item.data.events.data)

    def _extract_value_from_itemtree(self, item_tree: ItemTree) -> Optional[Any]:
        for element in item_tree.items:
            if isinstance(element, Element):
                value = self._value_from_element(element)
                if value is not None:
                    return value
            elif isinstance(element, ItemTree):
                value = self._extract_value_from_itemtree(element)
                if value is not None:
                    return value
        return None

    def _value_from_element(self, element: Element) -> Optional[Any]:
        return self._value_to_fhir(element.value)

    def _value_to_fhir(self, value: Any) -> Optional[Any]:
        if isinstance(value, DVQuantity):
            # Create quantity with proper FHIR structure and UCUM system
            return {
                'value': value.magnitude,
                'unit': value.units,
                'system': 'http://unitsofmeasure.org',  # UCUM system for standard units
                'code': self._unit_to_ucum_code(value.units)
            }
        if isinstance(value, DVCodedText):
            if value.code_string:
                # Determine the coding system based on terminology_id
                system = self._terminology_to_system(value.terminology_id)
                return {
                    'coding': [
                        {
                            'system': system,
                            'code': value.code_string,
                            'display': value.value,
                        }
                    ],
                    'text': value.value,
                }
            return value.value
        if isinstance(value, DVText):
            return value.value
        return value

    def _unit_to_ucum_code(self, unit_str: Optional[str]) -> Optional[str]:
        """Convert unit strings to UCUM codes."""
        if not unit_str:
            return None
        unit_str = str(unit_str)
        if 'Ã' in unit_str or 'Â' in unit_str:
            try:
                unit_str = unit_str.encode('latin-1').decode('utf-8')
            except UnicodeError:
                pass
        
        # Map common temperature and other units to UCUM codes
        unit_map = {
            '°C': 'Cel',  # Celsius
            'C': 'Cel',
            '°F': '[degF]',  # Fahrenheit
            'F': '[degF]',
            'kg': 'kg',  # Kilogram
            'g': 'g',  # Gram
            'mg': 'mg',  # Milligram
            'ml': 'mL',  # Milliliter
            'L': 'L',  # Liter
            'mmHg': 'mm[Hg]',  # Millimeters of mercury
            'bpm': '/min',  # Beats per minute
            'm': 'm',  # Meter
            'cm': 'cm',  # Centimeter
            'mm': 'mm',  # Millimeter
        }
        
        if unit_str == '°C':
            return 'Cel'
        if unit_str == '°F':
            return '[degF]'
        return unit_map.get(unit_str, unit_str)

    def _terminology_to_system(self, terminology_id: Optional[str]) -> str:
        """Map openEHR terminology ID to FHIR coding system URL."""
        if not terminology_id:
            return 'http://terminology.openehr.org/CodeSystem/local'
        
        terminology_map = {
            'local': 'http://terminology.openehr.org/CodeSystem/local',
            'SNOMED-CT': 'http://snomed.info/sct',
            'ICD-10': 'http://hl7.org/fhir/sid/icd-10',
            'ICD-10-CM': 'http://hl7.org/fhir/sid/icd-10-cm',
            'LOINC': 'http://loinc.org',
            'openehr': 'http://terminology.openehr.org/CodeSystem/local',
        }
        
        return terminology_map.get(terminology_id, f'http://terminology.openehr.org/CodeSystem/{terminology_id}')

    def _validate_against_opt_file(self, composition: Composition, opt_path: str) -> bool:
        if not os.path.isabs(opt_path):
            opt_path = os.path.join(os.getcwd(), opt_path)
        if not os.path.exists(opt_path):
            self.validation_messages.append(f'Configured OPT file does not exist: {opt_path}')
            return False
        if not composition.template_id:
            self.validation_messages.append('Composition does not contain archetype_details.template_id.value.')
            return False

        try:
            with open(opt_path, 'r', encoding='utf-8') as f:
                opt_text = f.read()
        except OSError as exc:
            self.validation_messages.append(f'Could not read OPT file {opt_path}: {exc}')
            return False

        template_marker = f'<value>{composition.template_id}</value>'
        if template_marker not in opt_text:
            self.validation_messages.append(
                f'OPT file does not appear to contain template_id {composition.template_id!r}.'
            )
            return False
        return True

    def _run_java_sdk_validator(
        self,
        validator_command: Union[str, List[str]],
        composition_source: str,
    ) -> bool:
        if isinstance(validator_command, str):
            command = validator_command.format(composition=composition_source)
            completed = subprocess.run(command, shell=True, capture_output=True, text=True)
        else:
            command = [part.format(composition=composition_source) for part in validator_command]
            completed = subprocess.run(command, shell=False, capture_output=True, text=True)

        if completed.returncode != 0:
            if completed.stderr:
                self.validation_messages.append(completed.stderr.strip())
            if completed.stdout:
                self.validation_messages.append(completed.stdout.strip())
            return False
        return True

    def build_bundle(self, resources: List[Dict[str, Any]], bundle_type: str = 'transaction') -> Dict[str, Any]:
        entries = [
            {
                'fullUrl': f"urn:uuid:{resource.get('id')}",
                'resource': resource,
                'request': {'method': 'POST', 'url': resource['resourceType']},
            }
            for resource in resources
        ]

        bundle = Bundle(type=bundle_type, entry=entries)
        if hasattr(bundle, 'model_dump'):
            return bundle.model_dump(mode='json', exclude_none=True)
        return json.loads(bundle.json(exclude_none=True))

    def send_bundle(self, bundle: Dict[str, Any], endpoint: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        if requests is None:
            raise RuntimeError(
                'The requests package is required to send bundles. Install requests or call build_bundle only.'
            )

        headers = headers or {'Content-Type': 'application/fhir+json'}
        response = requests.post(endpoint, json=bundle, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()


def load_mapping_config(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Transform openEHR composition JSON into a FHIR transaction bundle.'
    )
    parser.add_argument(
        '--composition',
        default='Corona_Anamnese_composition_example.json',
        help='openEHR composition JSON file.',
    )
    parser.add_argument(
        '--mapping',
        default='mapping_config_example.json',
        help='Mapping configuration JSON file.',
    )
    parser.add_argument(
        '--patient-demographics',
        help='Optional openEHR demographics JSON file to create a Patient resource.',
    )
    parser.add_argument(
        '--endpoint',
        help='Optional FHIR endpoint URL for posting the transaction bundle.',
    )
    parser.add_argument(
        '--output',
        help='Optional output path for writing the generated FHIR bundle as UTF-8 JSON.',
    )
    parser.add_argument(
        '--include-pdf',
        action='store_true',
        help='Generate a PDF summary and include it as a FHIR DocumentReference.',
    )

    args = parser.parse_args()
    mapping_config = load_mapping_config(args.mapping)
    transformer = OpenEHRToFHIRTransformer(mapping_config)

    composition = transformer.load_composition(args.composition)
    if not transformer.validate_composition(composition, composition_source=args.composition):
        raise ValueError('Composition failed validation: ' + '; '.join(transformer.validation_messages))

    resources = transformer.map_composition_to_resources(
        composition,
        patient_demographics=args.patient_demographics,
        include_pdf=args.include_pdf,
    )
    bundle = transformer.build_bundle(resources)

    if args.endpoint:
        response = transformer.send_bundle(bundle, args.endpoint)
        print(json.dumps(response, indent=2, ensure_ascii=False))
    elif args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
        print(f'FHIR bundle written to {args.output}')
    else:
        print(json.dumps(bundle, indent=2, ensure_ascii=False))
