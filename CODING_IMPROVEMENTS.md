# Coding, Terminology, and Mapping Improvements

## Summary

The transformer preserves more clinical coding and structure from the openEHR composition when producing FHIR resources. It now combines:

- openEHR datatype parsing
- terminology-aware `DV_CODED_TEXT` handling
- path-based value extraction
- mapped FHIR observation codes
- FHIR `Observation.component[]` support for additional openEHR values
- optional generated PDF summary as a FHIR `DocumentReference`

## openEHR Datatype Handling

### `DV_CODED_TEXT`

`openEHR_model.py` preserves:

- display text
- code string
- terminology ID

This allows the transformer to produce FHIR `CodeableConcept` values with the correct coding system.

Example openEHR local coded value:

```json
{
  "coding": [
    {
      "system": "http://terminology.openehr.org/CodeSystem/local",
      "code": "at0112",
      "display": "Ja"
    }
  ],
  "text": "Ja"
}
```

### `DV_QUANTITY`

Quantities are mapped to FHIR `Quantity` with:

- `value`
- `unit`
- UCUM `system`
- mapped UCUM `code`

Example body temperature:

```json
{
  "value": 37.6,
  "unit": "°C",
  "system": "http://unitsofmeasure.org",
  "code": "Cel"
}
```

## Terminology Mapping

The transformer maps openEHR terminology IDs to FHIR coding system URLs:

| openEHR terminology | FHIR system |
| --- | --- |
| `local` | `http://terminology.openehr.org/CodeSystem/local` |
| `openehr` | `http://terminology.openehr.org/CodeSystem/local` |
| `SNOMED-CT` | `http://snomed.info/sct` |
| `ICD-10` | `http://hl7.org/fhir/sid/icd-10` |
| `ICD-10-CM` | `http://hl7.org/fhir/sid/icd-10-cm` |
| `LOINC` | `http://loinc.org` |

Unknown terminology IDs fall back to:

```text
http://terminology.openehr.org/CodeSystem/{terminology_id}
```

## Observation Code Mapping

`mapping_config_example.json` assigns FHIR codes for the example observation archetypes:

| openEHR archetype | FHIR code |
| --- | --- |
| `openEHR-EHR-OBSERVATION.story.v1` | LOINC `34109-9` |
| `openEHR-EHR-OBSERVATION.symptom_sign_screening.v0` | LOINC `54899-0` |
| `openEHR-EHR-OBSERVATION.body_temperature.v2` | LOINC `8310-5` |
| `openEHR-EHR-OBSERVATION.exposure_assessment.v0` | LOINC `87909-4` |
| `openEHR-EHR-OBSERVATION.travel_history.v0` | LOINC `94651-7` |

If an archetype has no explicit coding in the mapping config, the transformer falls back to an openEHR archetype coding system.

## Path-Based Value Extraction

The parser flattens openEHR item trees into paths such as:

```text
/data/events/data/items[at0022]/items[at0005]
```

Mapping config can then target exact fields:

```json
{
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

This avoids the older behavior where only the first value in an observation was used.

## Observation Components

Questionnaire-like openEHR observations often contain more than one meaningful value. The transformer now maps secondary values into FHIR `Observation.component[]`.

Examples:

- Symptom screening maps the symptom text as `valueString` and the present/absent coded answer as a component.
- Exposure assessment maps the exposure agent as `valueString` and exposure presence as a component.
- Travel history maps the high-risk area answer as `valueCodeableConcept` and location text as a component.

## Unicode and Mojibake Repair

Some example input text contains common UTF-8-as-Latin-1 artifacts. The parser repairs common cases before mapping so output can contain readable text such as:

```text
Körpertemperatur
°C
```

The JSON output is written with `ensure_ascii=False`, so readable Unicode is preferred over escaped sequences where possible.

## PDF DocumentReference

When `--include-pdf`, `-IncludePdf`, or `include_pdf=true` is used, the transformer:

1. Generates a simple human-readable PDF summary from the parsed openEHR composition.
2. Base64-encodes the PDF.
3. Adds a FHIR `DocumentReference` to the transaction bundle.

The `DocumentReference.content[0].attachment` uses:

```json
{
  "contentType": "application/pdf",
  "data": "<base64-pdf>",
  "title": "Corona_Anamnese Composition Summary.pdf"
}
```

## Validation

The transformer performs lightweight validation:

- composition has content
- composition template ID matches the configured template ID
- configured OPT file exists and contains the expected template ID

For stronger validation, configure `template.java_validator_command` to call a Java sidecar built with the EHRbase openEHR SDK.

## Current Result

The example transform now produces:

- `Patient`
- `Encounter`
- 5 mapped `Observation` resources
- optional `DocumentReference` with embedded PDF

The focused test suite covers coding, path mapping, components, Unicode output, API behavior, PDF generation, and the HTML upload form.
