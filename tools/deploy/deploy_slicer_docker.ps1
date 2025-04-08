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

# Function to determine if one path is relative to another
function Test-PathRelative {
    param (
        [string]$BasePath,
        [string]$TargetPath
    )
    try {
        $resolvedBase = (Resolve-Path -Path $BasePath).Path
        $resolvedTarget = (Resolve-Path -Path $TargetPath).Path
        return $resolvedTarget.StartsWith($resolvedBase)
    } catch {
        return $false
    }
}

# Function to get the mount path for a given path.
# It avoids driver others than 'C:/' due to the docker container limitation
function Get-MountPath {
    param (
        [string]$Path
    )

    $mountPath = $Path
    if (-not (Test-PathRelative -BasePath "C:/" -TargetPath $Path)) {
        $pathDrive = Split-Path -Path $Path -Qualifier
        $mountPath = $Path -replace $pathDrive, "C:"
    }

    return $mountPath
}

# Function to retrieve only the unique paths from the path list, also considering the relative paths.
function Get-UniquePaths {
    param (
        [string[]]$Paths
    )

    $sortedPaths = $Paths | Sort-Object -Unique
    
    $uniquePaths = @()
    foreach ($currentPath in $sortedPaths) {
        if ($currentPath -in $uniquePaths) {
            continue
        }
        $isRelative = $false
        foreach ($uniquePath in $uniquePaths) {
            if (Test-PathRelative -BasePath $uniquePath -TargetPath $currentPath) {
                $isRelative = $true
            }
        }

        if (-not $isRelative) {
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
$repoPath = $repoPath -replace '\\', '/'
$outputDir = $OutputDir -replace '\\', '/'
$archiveParentDir = $archiveParentDir -replace '\\', '/'
$archiveFilePath = $Archive -replace '\\', '/'

$mountedRepoPath = Get-MountPath -Path $repoPath
$mountedOutputDir = Get-MountPath -Path $outputDir # "C:/output/" 
$mountedArchive = Get-MountPath -Path $archiveParentDir # "C:/archive/"
$archiveFileName = Split-Path -Path $archiveFilePath -Leaf
$mountedArchiveFilePath = Join-Path -Path $mountedArchive -ChildPath $archiveFileName

$volumePathsMap = @{}
$volumePathsMap["${repoPath}"] = $mountedRepoPath
$volumePathsMap["${outputDir}"] = $mountedOutputDir
$volumePathsMap["${archiveParentDir}"] = $mountedArchive

$volumePaths = @(
    "${repoPath}",
    "${outputDir}",
    "${archiveParentDir}"
)

$uniqueVolumePaths = Get-UniquePaths -Paths $volumePaths

# Construct the string for the volume arguments
$volumeArgs = @()
foreach ($path in $uniqueVolumePaths) {
    $mountPath = $volumePathsMap["${path}"]
    $volumeArgs += "--volume"
    $volumeArgs += "${path}:${mountPath}"
}

# Run the Docker Compose command
& $dockerComposeAlias run --rm -T ${volumeArgs} `
    --env PYTHONUNBUFFERED=1 `
    "${dockerServiceName}" `
    powershell -Command "python ${mountedRepoPath}/tools/deploy/deploy_slicer.py $mountedArchiveFilePath $Arguments --output-dir $mountedOutputDir"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to run the deploy script. Check the logs and try again."
    exit 6
}
