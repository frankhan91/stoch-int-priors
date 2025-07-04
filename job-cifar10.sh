#!/bin/bash
#SBATCH -p gpu
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --constraint=a100
#SBATCH --gpus-per-task=1
#SBATCH --cpus-per-task=2
#SBATCH --time=72:00:00
#SBATCH -o logs/r%x.o%j

export OMP_NUM_THREADS=1

module load modules/2.3-20240529
source /mnt/home/cmodi/envs/torchlatest/bin/activate

corruption=$1
clevel=$2
nlevel=$3
mlevel=$4
echo $corruption
echo $clevel
echo $nlevel

dataset='cifar10'
# dataset='celebA'
channels=64
trainsteps=50_000
time python -u deconvolving_interpolants.py \
                 --dataset $dataset --corruption $corruption \
                --corruption_level $clevel $nlevel $mlevel --train_steps $trainsteps \
                --channels $channels  --ode_steps 64 --alpha 0.9 --resamples 2  \
                --lr_scheduler --suffix "v3" --learning_rate 0.0005
