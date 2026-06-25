# OpenEHR Coding and Terminology Improvements

## Summary of Changes

The transformer now properly preserves and uses openEHR coding/terminology in FHIR resources, addressing concerns about strange transformations losing clinical coding information.

## Key Improvements

### 1. Enhanced OpenEHR Data Model (openEHR_model.py)

**DVCodedText Class Enhancement:**
- Added `terminology_id` field to preserve the terminology system (e.g., "local", "SNOMED-CT", "ICD-10")
- Previously: Lost terminology information, only kept code string
- Now: Preserves full coding context

### 2. Improved Value Extraction (openEHR_to_FHIR_transformer.py)

**New Terminology Mapping Method:**
- Added `_terminology_to_system()` method to map openEHR terminology IDs to FHIR coding system URLs
- Maps "local" → http://terminology.openehr.org/CodeSystem/local
- Maps "SNOMED-CT" → http://snomed.info/sct
- Maps "ICD-10" → http://hl7.org/fhir/sid/icd-10
- Maps unknown → http://terminology.openehr.org/CodeSystem/{terminology_id}

**Enhanced Value Handling:**
- Updated `_value_from_element()` to use proper terminology systems instead of hardcoded v2-0136
- Now correctly creates valueCodeableConcept with proper coding system from openEHR terminology

### 3. Observation Code Mapping (openEHR_to_FHIR_transformer.py)

**New Observation Code Extraction:**
- Added `_extract_observation_code()` method
- Uses archetype mapping to look up LOINC/SNOMED codes for observation types
- Falls back to archetype-based coding if not in mapping
- Creates proper FHIR CodeableConcept structures with system + code + display

**Archetype-to-Coding Conversion:**
- Added `_archetype_to_coding()` method
- Converts openEHR archetype IDs to coding format
- Example: "openEHR-EHR-OBSERVATION.body_temperature.v2" → {system: "http://terminology.openehr.org/CodeSystem/openehr-archetypes", code: "body_temperature"}

### 4. Enhanced Mapping Configuration (mapping_config_example.json)

Added LOINC codes for each observation type:
- story.v1 → 34109-9 (History of Problem)
- symptom_sign_screening.v0 → 54899-0 (Symptom screening)
- body_temperature.v2 → 8310-5 (Body temperature)
- exposure_assessment.v0 → 87909-4 (Exposure assessment)
- travel_history.v0 → 94651-7 (Travel history)

Added `terminology_system` field for fallback coding system

## Before vs After

### Before
```json
{
  "code": {"text": "Körpertemperatur"}
}
```

### After
```json
{
  "code": {
    "coding": [
      {
        "system": "http://loinc.org",
        "code": "8310-5",
        "display": "Body temperature"
      }
    ],
    "text": "Körpertemperatur"
  }
}
```

## Value Coding Preservation

### Before (Travel History observation value)
```json
{
  "valueCodeableConcept": {
    "coding": [
      {
        "system": "http://terminology.hl7.org/CodeSystem/v2-0136",
        "code": "at0112",
        "display": "Ja"
      }
    ]
  }
}
```

### After (With Proper Terminology System)
```json
{
  "valueCodeableConcept": {
    "coding": [
      {
        "system": "http://terminology.openehr.org/CodeSystem/local",
        "code": "at0112",
        "display": "Ja"
      }
    ]
  }
}
```

## Implementation Details

### File Changes

1. **openEHR_model.py**
   - Enhanced DVCodedText to capture terminology_id
   - Updated _parse_value() to extract full code information

2. **openEHR_to_FHIR_transformer.py**
   - New: _extract_observation_code() - extracts codes with mapping support
   - New: _archetype_to_coding() - converts archetypes to FHIR coding
   - New: _terminology_to_system() - maps terminology IDs to system URLs
   - Updated: _map_observation() - uses _extract_observation_code()
   - Updated: _value_from_element() - uses proper terminology systems

3. **mapping_config_example.json**
   - Added "coding" field with LOINC codes for each observation archetype
   - Added "terminology_system" for fallback coding

## Result

All 5 observations in the example bundle now have:
✓ Proper LOINC codes from mapping
✓ Full CodeableConcept structures for both observation codes and values
✓ Correct terminology system references (LOINC for observations, local for openEHR codes)
✓ Preserved openEHR codes in value fields
✓ Proper FHIR validation

## Extensibility

The mapping configuration is extensible:
- Add more archetypes with their LOINC/SNOMED codes
- Map specific value codes to standard terminologies
- Override the terminology system per archetype
- Support custom coding system mappings
