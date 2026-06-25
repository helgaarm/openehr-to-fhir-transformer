# openEHR to FHIR Transformer

Python tooling for transforming example openEHR compositions into validated FHIR transaction bundles.

The project currently supports:

- Parsing openEHR JSON compositions into lightweight Python models.
- Lightweight template validation against `Corona_Anamnese.opt`.
- Path-based openEHR value extraction and mapping.
- FHIR `Patient`, `Encounter`, `Observation`, and optional `DocumentReference` generation.
- Optional generated PDF summary embedded in the FHIR bundle.
- Flask API, Python client, PowerShell runner, and unit tests.

## Quick Start

From this directory:

```powershell
py -m venv ..\.venv
.\run.ps1 -Mode install
.\run.ps1 -Mode test
.\run.ps1 -Mode transform -Output output_bundle.json
```

`run.ps1` uses the virtual environment at `..\.venv\Scripts\python.exe`, so create that environment first on a fresh checkout.

Include a generated PDF summary in the bundle:

```powershell
.\run.ps1 -Mode transform -Output output_with_pdf.json -IncludePdf
```

Start the API:

```powershell
.\run.ps1 -Mode api
```

Then open:

```text
http://localhost:5000
```

## Documentation

- [Transformer README](README_FHIR_transformer.md): CLI, workflow, path-based mapping, validation hooks, and PDF `DocumentReference`.
- [API README](API_README.md): Flask endpoints, request/response examples, Python client usage.
- [Coding improvements](CODING_IMPROVEMENTS.md): terminology/coding, path mapping, components, and Unicode handling.

## Example Output

Default transform creates a FHIR transaction bundle with:

- `Patient`
- `Encounter`
- mapped `Observation` resources

With `-IncludePdf` or `include_pdf=true`, the bundle also includes:

- `DocumentReference` with an embedded base64 `application/pdf` attachment

## Tests

```powershell
.\run.ps1 -Mode test
```

Current focused test suite covers parsing, path-based mapping, components, Unicode output, API behavior, PDF `DocumentReference`, and the HTML upload form.
