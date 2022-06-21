#!/bin/sh
#SBATCH -A tcr
#SBATCH -n 1
#SBATCH -J $JOBNAME
#SBATCH --time=999:99:99
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=3

#source ~/.bashrc

cd $WORK_DIR

module purge
module load anaconda3/5.0.1
conda activate microtom
$COMMANDS

module unload anaconda3/5.0.1
