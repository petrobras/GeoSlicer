#PBS -N $JOBNAME
#PBS -l nodes=1:ppn=$PPN,mem=$MEM
#PBS -m ea 
#PBS -M `whoami`@petrobras.com.br
#PBS -j eo
#PBS -l walltime=240:00:00

source ~/.bashrc

cd $WORK_DIR

module purge
module load anaconda3/5.0.1
conda activate microtom
$COMMANDS

module unload anaconda3/5.0.1
