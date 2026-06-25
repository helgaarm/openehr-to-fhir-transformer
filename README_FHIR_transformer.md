# openEHR to FHIR Transformation

This module transforms an openEHR composition JSON document into FHIR resources and wraps them in a FHIR transaction `Bundle`.

## Files

- `openEHR_to_FHIR_transformer.py`: CLI transformer. Loads openEHR JSON, validates template metadata, maps resources, builds a FHIR bundle, and can post it to a FHIR endpoint.
- `openEHR_model.py`: Lightweight parser for the openEHR JSON structures used by the example composition. It repairs common mojibake and flattens item trees into path-addressable values.
- `mapping_config_example.json`: Example mapping configuration from openEHR archetype IDs and element paths to FHIR resource types, profiles, fields, components, and codes.
- `pdf_document.py`: Small built-in PDF writer used for generated summary attachments.
- `fhir_api.py`: Flask API wrapper around the transformer.
- `fhir_client.py`: Python client for the Flask API.
- `run.ps1`: PowerShell helper for install, transform, API, and test runs.
- `Corona_Anamnese_composition_example.json`: Example openEHR composition payload.
- `Corona_Anamnese.opt`: Example operational template used for lightweight template metadata checks.
- `person.json`: Optional demographics payload used to create the `Patient`.

## Setup

PowerShell:

```powershell
py -m venv ..\.venv
.\run.ps1 -Mode install
```

`run.ps1` expects Python at `..\.venv\Scripts\python.exe` relative to this directory.

Manual:

```bash
pip install -r requirements.txt
pip install pytest
```

The project uses `fhir.resources==7.1.0`, which serializes validated FHIR models using the Pydantic v1-style `.json()` and `.dict()` APIs.

## Workflow

1. Load an openEHR composition JSON file.
2. Parse the composition into lightweight Python dataclasses.
3. Validate basic template metadata against the configured `.opt` file.
4. Create a `Patient` from optional demographics, or create a placeholder patient if demographics are omitted.
5. Create an `Encounter` from composition context.
6. Recursively flatten openEHR `ELEMENT` values into path-addressable values.
7. Map configured openEHR content items to FHIR resources using archetype IDs and field paths.
8. Optionally generate a PDF summary and add it as a FHIR `DocumentReference`.
9. Build a FHIR transaction `Bundle`.
10. Optionally send the bundle to a FHIR endpoint.

## CLI Usage

Run with the example files:

```bash
python openEHR_to_FHIR_transformer.py
```

Run with explicit files and optional demographics:

```bash
python openEHR_to_FHIR_transformer.py \
  --composition Corona_Anamnese_composition_example.json \
  --mapping mapping_config_example.json \
  --patient-demographics person.json
```

Write the generated bundle to a UTF-8 JSON file:

```bash
python openEHR_to_FHIR_transformer.py \
  --composition Corona_Anamnese_composition_example.json \
  --mapping mapping_config_example.json \
  --patient-demographics person.json \
  --output output_bundle.json
```

Include a generated PDF summary as a FHIR `DocumentReference`:

```bash
python openEHR_to_FHIR_transformer.py \
  --composition Corona_Anamnese_composition_example.json \
  --mapping mapping_config_example.json \
  --patient-demographics person.json \
  --include-pdf \
  --output output_with_pdf.json
```

PowerShell helper:

```powershell
.\run.ps1 -Mode transform -Output output_bundle.json
.\run.ps1 -Mode transform -Output output_with_pdf.json -IncludePdf
.\run.ps1 -Mode api
.\run.ps1 -Mode test
```

## API Usage

Start the Flask API:

```bash
python fhir_api.py
```

Or:

```powershell
.\run.ps1 -Mode api
```

Transform using uploaded files:

```bash
curl -X POST http://localhost:5000/transform \
  -F "composition=@Corona_Anamnese_composition_example.json" \
  -F "mapping=@mapping_config_example.json" \
  -F "demographics=@person.json" \
  -F "include_pdf=true"
```

Transform using JSON:

```json
{
  "composition": { "...": "openEHR composition JSON" },
  "mapping": { "...": "mapping config JSON" },
  "demographics": { "...": "optional demographics JSON" },
  "include_pdf": true
}
```

The transformer accepts demographics both as a file path in CLI usage and as an already parsed JSON object in API usage.

## Path-Based Mapping

The parser flattens observation values into openEHR-style paths. Mapping entries can target those paths with a `fields` object:

```json
{
  "archetype_id": "openEHR-EHR-OBSERVATION.symptom_sign_screening.v0",
  "resource_type": "Observation",
  "fields": {
    "effectiveDateTime": "/data/events/time",
    "valueString": "/data/events/data/items[at0022]/items[at0004]",
    "components": [
      {
        "path": "/data/events/data/items[at0022]/items[at0005]",
        "code": {
          "text": "Present?"
        },
        "value_field": "valueCodeableConcept"
      }
    ]
  }
}
```

Supported main value fields are `valueString`, `valueQuantity`, and `valueCodeableConcept`. Component mappings support the same value types through `value_field`.

## Template and Java SDK Validation Hook

The mapping config can declare expected template metadata:

```json
{
  "template": {
    "template_id": "Corona_Anamnese",
    "opt_path": "Corona_Anamnese.opt",
    "java_validator_command": null
  }
}
```

The built-in validation checks that the composition has content, that the composition template ID matches the mapping config, and that the configured OPT file contains that template ID.

For fuller openEHR validation, keep Python as the FHIR mapping layer and add a Java SDK sidecar command later. Set `java_validator_command` to either a command string or command argument array. The placeholder `{composition}` is replaced with the composition file path when running from the CLI.

## Output Notes

- The default output is a FHIR transaction `Bundle`.
- Generated resources currently include `Patient`, `Encounter`, and configured `Observation` resources.
- Repeated mapped archetypes get stable numeric ID suffixes, so transaction bundle `fullUrl` values remain unique.
- UTC timestamps are emitted by the installed FHIR library as `+00:00`, for example `2024-06-25T10:00:00+00:00`.
- Quantity values include the UCUM system and mapped UCUM code when a known unit is found, for example Celsius to `Cel`.
- Common mojibake in source text is repaired while parsing, for example mis-decoded German characters and degree symbols.
- Questionnaire-like observations can preserve extra openEHR elements as FHIR `Observation.component[]`.
- If `--include-pdf` or `include_pdf=true` is used, the bundle includes a FHIR `DocumentReference` with an embedded base64 PDF attachment generated from the parsed openEHR composition.

## Tests

Run tests:

```powershell
.\run.ps1 -Mode test
```

Or manually:

```bash
python -m pytest test_openEHR_to_FHIR_transformer.py -q -p no:cacheprovider
```

`-p no:cacheprovider` avoids local pytest cache directory issues on restricted Windows workspaces.

## Extension Points

- Replace the lightweight OPT check with full EHRbase openEHR SDK validation.
- Implement a Java sidecar validator that uses the existing `template.java_validator_command` hook with EHRbase SDK validation, OPT, and serialization modules.
- Extend `mapping_config_example.json` with additional archetypes, paths, FHIR profiles, components, and terminology mappings.
- Add mappings for `Condition`, `MedicationRequest`, `Procedure`, or other FHIR resources as needed.

## Limitations

This is still a boilerplate transformer. It parses the example openEHR JSON shape directly and performs only lightweight template checks unless an external Java validator is configured. Adapt the parser and mapping logic to your source template and target FHIR implementation guide before using it for production data.
