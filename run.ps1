param(
    [ValidateSet("transform", "api", "test", "install")]
    [string]$Mode = "transform",

    [string]$Composition = "Corona_Anamnese_composition_example.json",
    [string]$Mapping = "mapping_config_example.json",
    [string]$Demographics = "person.json",
    [string]$Output = "",
    [switch]$IncludePdf
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Set-Location $ScriptDir

switch ($Mode) {
    "install" {
        & $Python -m pip install -r requirements.txt pytest
    }

    "test" {
        & $Python -m pytest test_openEHR_to_FHIR_transformer.py -q -p no:cacheprovider
    }

    "api" {
        & $Python fhir_api.py
    }

    "transform" {
        $argsList = @(
            "openEHR_to_FHIR_transformer.py",
            "--composition", $Composition,
            "--mapping", $Mapping
        )

        if ($Demographics -and (Test-Path $Demographics)) {
            $argsList += @("--patient-demographics", $Demographics)
        }

        if ($IncludePdf) {
            $argsList += @("--include-pdf")
        }

        if ($Output) {
            if (Test-Path $Output) {
                Remove-Item -LiteralPath $Output -Force
            }
            $argsList += @("--output", $Output)
            & $Python @argsList
        }
        else {
            & $Python @argsList
        }
    }
}
