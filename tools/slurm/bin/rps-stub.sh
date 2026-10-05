#!/bin/bash
# Stands in for the cluster's rps.sh, which normally runs the GeoSlicer CLI
# inside a Singularity/Apptainer image on a compute node.
#
# Called as:
#   bash rps.sh --sif <image> [--gpu 1] [--time "..."] [--cmd '...'] [--cli '...']
#
# Prints "job_id = <slurm id>" on stdout, which is the only thing the calling
# handler looks for. stderr is kept empty: a non-empty stderr fails the job.
set -uo pipefail

SIF=""
USE_GPU=0
TIME_LIMIT=""
declare -a PY_CMDS=()
declare -a CLI_CMDS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --sif)  SIF="${2:-}"; shift 2 ;;
        --gpu)  USE_GPU="${2:-1}"; shift 2 ;;
        --time) TIME_LIMIT="${2:-}"; shift 2 ;;
        --cmd)  PY_CMDS+=("${2:-}"); shift 2 ;;
        --cli)  CLI_CMDS+=("${2:-}"); shift 2 ;;
        *)      shift ;;
    esac
done

JOB_DIR="$PWD"
DURATION="${SLURMLAB_JOB_SECONDS:-20}"
if [ "$USE_GPU" != "0" ]; then
    PARTITION="${SLURMLAB_GPU_PARTITION:-gpu}"
else
    PARTITION="${SLURMLAB_PARTITION:-cpu}"
fi

# A real image means we can actually run the CLI; a placeholder means we can
# only simulate the job. Apptainer images start with the SIF magic.
RUNNER="simulate"
if [ -s "$SIF" ] && command -v apptainer >/dev/null 2>&1 && head -c 8 "$SIF" | grep -q "SIF_MAGIC"; then
    RUNNER="apptainer"
fi

batch="${JOB_DIR}/run_geoslicer_cli.sh"
{
    echo '#!/bin/bash'
    echo "#SBATCH --job-name=geoslicer_cli"
    echo "#SBATCH --partition=${PARTITION}"
    echo "#SBATCH --output=${JOB_DIR}/slurm-%j.out"
    echo "#SBATCH --ntasks=1"
    [ -n "$TIME_LIMIT" ] && echo "#SBATCH --time=${TIME_LIMIT}"
    echo 'set -uo pipefail'
    echo "cd \"${JOB_DIR}\""
    echo "echo \"geoslicer cli job \${SLURM_JOB_ID} on \$(hostname), runner=${RUNNER}\""
    for cli in ${CLI_CMDS[@]+"${CLI_CMDS[@]}"}; do
        [ -n "$cli" ] || continue
        echo "echo \"--cli ${cli}\""
        if [ "$RUNNER" = "apptainer" ]; then
            echo "apptainer exec --bind /nethome --bind /atena \"${SIF}\" python-real -m ${cli}"
        fi
    done
    for cmd in ${PY_CMDS[@]+"${PY_CMDS[@]}"}; do
        [ -n "$cmd" ] || continue
        echo "echo \"--cmd ${cmd}\""
        if [ "$RUNNER" = "apptainer" ]; then
            echo "apptainer exec --bind /nethome --bind /atena \"${SIF}\" python-real -c ${cmd}"
        fi
    done
    if [ "$RUNNER" != "apptainer" ]; then
        echo "echo 'no GeoSlicer CLI image available: simulating the run'"
        echo "sleep ${DURATION}"
        echo "echo 'simulated run complete (no result files were produced)'"
    fi
    echo 'exit $?'
} > "$batch"
chmod 0777 "$batch"

submit="$(sbatch "$batch" 2>&1)"
JOBID="$(printf '%s' "$submit" | grep -oE '[0-9]+$' | tail -1)"

if [ -z "$JOBID" ]; then
    echo "sbatch failed: ${submit}"
    exit 1
fi

printf '%s\n' "$JOBID" > "${JOB_DIR}/job_id"
echo "job_id = ${JOBID}"
echo "work_dir = ${JOB_DIR}"
echo "slurm_file = ${JOB_DIR}/slurm-${JOBID}.out"
