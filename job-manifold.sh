#!/bin/bash
#SBATCH -p gpu
#SBATCH --ntasks=1
##SBATCH --mem=32G
#SBATCH --nodes=1
#SBATCH --constraint='a100'
#SBATCH --gpus-per-task=1
#SBATCH --cpus-per-task=2
#SBATCH --time=10:00:00
#SBATCH -o logs/r%x.%j.out

export OMP_NUM_THREADS=1
source /mnt/home/${USER}/.zshrc
conda activate /mnt/home/jhan/miniforge3/envs/edm

python -u mlp_interpolants_trainer.py \
    --dataset manifold_ds \
    --corruption projection_vec_ds \
    --corruption_level 2 0.01 \
    --gamma_scale 1.0 \
    --train_steps 200000 \
    --learning_rate 5e-4 \
    --clean_data_steps -1 \
    --batch_size 4096 \
    --update_transport_every 32 \
    --suffix up32_gamma1