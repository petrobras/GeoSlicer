# Deploy slicerltrace application script wrapper within a docker container.
# The arguments will be passed to the deploy_slicer.py call, but it will check if the '--output-dir' argument exists.
# If the 'output-dir' argument doesn't exist, then the script will not execute.

param (
    [string]$OutputDir = "",
    [switch]$BuildDocker = $false,
    [switch]$Help = $false
)

[string[]]$Arguments = $args

# Function to show help information
function Show-Help {
    Write-Host "Deploy slicerltrace application script wrapper within a docker container."
    Write-Host "Use the same flags as used in the python script deploy_slicer.py and define the output directory."
    Write-Host ""
    Write-Host "$(Split-Path -Leaf $MyInvocation.MyCommand.Path) [options] application [arguments]"
    Write-Host ""
    Write-Host "options:"
    Write-Host "-h, -Help                Show brief help"
    Write-Host "-b, -BuildDocker               Build docker image"
    Write-Host "-o, -OutputDir=DIR       Specify a directory to store output in"
}

# Function to normalize paths
function Normalize-Path {
    param ([string]$Path)
    if (-not $Path) { return "" }
    $normalized = $Path -replace '[/\\]+', '/'
    $normalized = $normalized -replace '/$', ''
    return $normalized
}

# Function to determine if one path is relative to another
function Test-PathRelative {
    param (
        [string]$BasePath,
        [string]$TargetPath
    )
    if ((-not $BasePath) -or (-not $TargetPath)) { return $false }
    $normBase = (Normalize-Path $BasePath).ToLower()
    $normTarget = (Normalize-Path $TargetPath).ToLower()
    
    if ($normBase -eq $normTarget) { return $true }
    if ($normTarget.StartsWith($normBase + "/")) { return $true }
    
    return $false
}

# Function to get the mount path for a given path.
# It avoids driver others than 'C:/' due to the docker container limitation
function Get-MountPath {
    param (
        [string]$Path
    )

    $normPath = Normalize-Path $Path
    $mountPath = $normPath
    if (-not $normPath.ToLower().StartsWith("c:/")) {
        $pathDrive = $normPath.Split(":")[0] + ":"
        $mountPath = $normPath -replace "^$pathDrive", "C:"
    }

    return $mountPath
}

# Function to retrieve only the unique paths from the path list, also considering the relative paths.
function Get-UniquePaths {
    param (
        [string[]]$Paths
    )

    $normalizedPaths = $Paths | ForEach-Object { Normalize-Path $_ } | Where-Object { $_ -ne "" } | Sort-Object -Unique
    $sortedPaths = $normalizedPaths | Sort-Object Length
    
    $uniquePaths = @()
    foreach ($currentPath in $sortedPaths) {
        $alreadyCovered = $false
        foreach ($uniquePath in $uniquePaths) {
            if (Test-PathRelative -BasePath $uniquePath -TargetPath $currentPath) {
                $alreadyCovered = $true
                break
            }
        }

        if (-not $alreadyCovered) {
            $uniquePaths += $currentPath    
        }
    }

    return $uniquePaths
}

if (-not $OutputDir) {
    Write-Host "Error: The argument '-OutputDir' is missing." -ForegroundColor Red
    exit 1
}

[string]$Archive = $null

# Find archive within arguments list
foreach ($arg in $Arguments) {
    if ((Test-Path -Path $arg -PathType Leaf) -or (Test-Path -PathType Container -Path $arg)) {
        $Archive = $arg
        $Arguments = $Arguments | Where-Object { $_ -ne $Archive }
        break
    }
}

if ((-not $Archive) -or ([string]::IsNullOrWhiteSpace($Archive))) {
    Write-Host "Error: Invalid archive path provided." -ForegroundColor Red
    exit 1
}

# Check for Docker Compose installation
$dockerComposeAlias = ""
if (Get-Command "docker compose" -ErrorAction SilentlyContinue) {
    $dockerComposeAlias = "docker compose"
} elseif (Get-Command "docker-compose" -ErrorAction SilentlyContinue) {
    $dockerComposeAlias = "docker-compose"
} else {
    Write-Error "Docker compose is not installed. Please install it and try again."
    exit 2
}

$dockerServiceName =  "slicerltrace-windows"

Write-Host "Output Directory: $OutputDir"
Write-Host "Build Docker: $($BuildDocker.IsPresent)"
Write-Host "Archive: $Archive"
Write-Host "Arguments: $Arguments"

# Build docker image
if ($BuildDocker) {
    Write-Host "Docker build flag is set. Proceeding with the Docker image build..."
    & $dockerComposeAlias build $dockerServiceName
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to build the Docker image. Check the logs and try again."
        exit 4
    }
}

# Get the Git repository root path
$repoPath = & git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Error: This script must be run inside a Git repository."
    exit 5
}

# Get the parent directory of the archive
$archiveParentDir = [System.IO.Path]::GetDirectoryName($Archive)
$repoPath = Normalize-Path $repoPath
$outputDir = Normalize-Path $OutputDir
$archiveParentDir = Normalize-Path $archiveParentDir
$archiveFilePath = Normalize-Path $Archive

$mountedRepoPath = Get-MountPath -Path $repoPath
$mountedOutputDir = Get-MountPath -Path $outputDir
$mountedArchive = Get-MountPath -Path $archiveParentDir
$archiveFileName = Split-Path -Path $archiveFilePath -Leaf
$mountedArchiveFilePath = Normalize-Path (Join-Path -Path $mountedArchive -ChildPath $archiveFileName)

Write-Host "Mounted Repo Path: $mountedRepoPath"
Write-Host "Mounted Output Dir: $mountedOutputDir"
Write-Host "Mounted Archive Path: $mountedArchiveFilePath"


$volumePathsMap = @{}
$volumePathsMap["$repoPath"] = $mountedRepoPath
$volumePathsMap["$outputDir"] = $mountedOutputDir
$volumePathsMap["$archiveParentDir"] = $mountedArchive

$volumePaths = @(
    $repoPath,
    $outputDir,
    $archiveParentDir
)

Write-Host "volumePaths: $volumePaths"
$uniqueVolumePaths = Get-UniquePaths -Paths $volumePaths
Write-Host "uniqueVolumePaths: $uniqueVolumePaths"

# Construct the string for the volume arguments
$volumeArgs = @()
foreach ($path in $uniqueVolumePaths) {
    $mountPath = $volumePathsMap["${path}"]
    $volumeArgs += "--volume"
    $volumeArgs += "${path}:${mountPath}"
}

Write-Host "volumeArgs: $volumeArgs"

# Create a clean array of arguments to prevent quoting/expansion issues
$dockerArgs = @(
    "run", "--rm", "-T"
)
$dockerArgs += $volumeArgs
$dockerArgs += @(
    "--env", "PYTHONUNBUFFERED=1",
    $dockerServiceName,
    "powershell",
    "-Command", "python ${mountedRepoPath}/tools/deploy/deploy_slicer.py $mountedArchiveFilePath $Arguments --output-dir $mountedOutputDir"
)

Write-Host "Executing deployment inside Docker..."
Write-Host "Command: $dockerComposeAlias $($dockerArgs -join ' ')"

# Run Docker Compose: merge stderr to stdout (2>&1) and force to string
& $dockerComposeAlias $dockerArgs 2>&1 | ForEach-Object { Write-Output $_.ToString() }

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to run the deploy script. Container exited with code $LASTEXITCODE. Check the Docker logs above."
    exit 6
}