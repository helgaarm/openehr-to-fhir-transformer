# openEHR to FHIR Transformation API

## Overview

`fhir_api.py` exposes the openEHR to FHIR transformer as a Flask API. It accepts an openEHR composition, a mapping configuration, and optional demographics data, then returns a FHIR transaction `Bundle`.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the API server:

```bash
python fhir_api.py
```

The server starts on `http://localhost:5000`.

## Endpoints

### GET /health

Returns service health.

```bash
curl http://localhost:5000/health
```

Example response:

```json
{
  "status": "healthy",
  "service": "openEHR-to-FHIR-API"
}
```

### POST /transform

Transforms uploaded JSON files.

Content type: `multipart/form-data`

| Parameter | Required | Description |
| --- | --- | --- |
| `composition` | Yes | openEHR composition JSON file |
| `mapping` | Yes | Mapping configuration JSON file |
| `demographics` | No | Patient demographics JSON file |
| `include_pdf` | No | Set to `true` to add a generated PDF summary as a FHIR `DocumentReference` |

Example:

```bash
curl -X POST http://localhost:5000/transform \
  -F "composition=@Corona_Anamnese_composition_example.json" \
  -F "mapping=@mapping_config_example.json" \
  -F "demographics=@person.json" \
  -F "include_pdf=true"
```

ePrescription example:

```bash
curl -X POST http://localhost:5000/transform \
  -F "composition=@ePrescription_prefilled_example.json" \
  -F "mapping=@ePrescription_mapping_config.json"
```

### POST /transform/json

Transforms a JSON request body. `demographics` is optional.

```json
{
  "composition": { "...": "openEHR composition JSON" },
  "mapping": { "...": "mapping config JSON" },
  "demographics": { "...": "optional demographics JSON" },
  "include_pdf": true
}
```

Example:

```bash
curl -X POST http://localhost:5000/transform/json \
  -H "Content-Type: application/json" \
  -d @payload.json
```

### GET /api/docs

Returns endpoint metadata.

```bash
curl http://localhost:5000/api/docs
```

## Response Format

Successful responses have this shape:

```json
{
  "success": true,
  "bundle": {
    "resourceType": "Bundle",
    "type": "transaction",
    "entry": []
  },
  "resource_count": 7
}
```

The bundle entries include `Patient`, `Encounter`, and configured resources such as `Observation` or `MedicationRequest`. If `include_pdf` is true, the last resource is a `DocumentReference` containing a base64 encoded `application/pdf` attachment.

## Request Data

### Mapping Config

The current mapping format uses a `mappings` array:

```json
{
  "template": {
    "template_id": "Corona_Anamnese",
    "opt_path": "Corona_Anamnese.opt",
    "java_validator_command": null
  },
  "patient_profile": "http://hl7.org/fhir/StructureDefinition/Patient",
  "encounter_profile": "http://hl7.org/fhir/StructureDefinition/Encounter",
  "terminology_system": "http://terminology.openehr.org/CodeSystem/openehr-archetypes",
  "mappings": [
    {
      "archetype_id": "openEHR-EHR-OBSERVATION.story.v1",
      "resource_type": "Observation",
      "fhir_profile": "http://hl7.org/fhir/StructureDefinition/Observation",
      "coding": {
        "system": "http://loinc.org",
        "code": "34109-9",
        "display": "History of Problem"
      },
      "fields": {
        "effectiveDateTime": "/data/events/time",
        "valueString": "/data/events/data/items[at0004]"
      }
    }
  ]
}
```

Observation mappings can target exact flattened openEHR paths. Extra values can be mapped into FHIR `Observation.component[]` using `fields.components`.

The ePrescription example uses `ePrescription_mapping_config.json` to map `openEHR-EHR-INSTRUCTION.medication_order.v0` to a FHIR `MedicationRequest`. Use `ePrescription_prefilled_example.json` for readable sample values. The ePrescription mapping uses `field_mappings` with dotted FHIR targets such as `medication.concept.text` and `dosageInstruction[0].route.text`.

### Demographics

Demographics may be supplied as an uploaded file or as the `demographics` object in `/transform/json`.

```json
{
  "uid": {
    "value": "6bb18d27-edad-4c4a-8d0a-da351194aa30"
  },
  "archetype_details": {
    "archetype_id": {
      "value": "openEHR-DEMOGRAPHIC-PERSON.person.v0"
    }
  },
  "content": [
    {
      "name": "Ritika"
    }
  ]
}
```

When demographics are provided, the generated `Patient` uses the demographics UID and name, and the generated resources reference that patient.

## Python Client

```python
import json
from fhir_client import FHIRTransformationClient

client = FHIRTransformationClient()

result = client.transform_files(
    "Corona_Anamnese_composition_example.json",
    "mapping_config_example.json",
    "person.json",
    include_pdf=True,
)

bundle = result["bundle"]
```

For JSON body usage:

```python
import json
from fhir_client import FHIRTransformationClient

client = FHIRTransformationClient()

with open("Corona_Anamnese_composition_example.json", encoding="utf-8") as f:
    composition = json.load(f)
with open("mapping_config_example.json", encoding="utf-8") as f:
    mapping = json.load(f)
with open("person.json", encoding="utf-8") as f:
    demographics = json.load(f)

result = client.transform_json(
    composition=composition,
    mapping=mapping,
    demographics=demographics,
    include_pdf=True,
)
```

## Testing

Run the unit tests:

```bash
pip install pytest
python -m pytest test_openEHR_to_FHIR_transformer.py -q -p no:cacheprovider
```

Run the client against a local API server:

```bash
python fhir_client.py Corona_Anamnese_composition_example.json mapping_config_example.json output_bundle.json person.json --include-pdf
```

## Notes

- `fhir.resources==7.1.0` validates the generated FHIR models.
- UTC timestamps are serialized as offsets, for example `2024-06-25T10:00:00+00:00`.
- `include_pdf` generates a simple human-readable PDF from the parsed openEHR composition and embeds it in a FHIR `DocumentReference`.
- The API has a default upload limit of 50 MB through `MAX_CONTENT_LENGTH`.
- `validate_composition()` checks basic content, template ID, and configured OPT metadata. Configure `template.java_validator_command` to call a Java openEHR SDK validator sidecar for fuller validation.

## Troubleshooting

If `curl` cannot connect to port 5000, start the API with:

```bash
python fhir_api.py
```

If JSON parsing fails, validate the input file:

```bash
python -m json.tool composition.json
```

If a request returns `Missing required files` or `Missing required fields`, provide both `composition` and `mapping`. Demographics are optional.
