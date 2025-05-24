import sys, os
import torch
torch.backends.cuda.matmul.allow_tf32 = True
torch.set_float32_matmul_precision('high')
from torch.utils.data import DataLoader
import numpy as np
from tqdm import tqdm

sys.path.append('./src/')
from utils import count_parameters, infinite_dataloader, grab
from nets import SimpleFeedForward, FeedForwardwithEMB
from custom_datasets import ManifoldDataset, Manifold_A_Dataset
from distribution import DistributionDataLoader, distribution_dict
from interpolant_utils import DeconvolvingInterpolant, save_fig_checker, save_fig_manifold
from trainer_si_mlp import TrainerMLP
import forward_maps as fwd_maps
import argparse
import matplotlib.pyplot as plt

BASEPATH = '/mnt/home/jhan/stoch-int-priors/results'
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print("DEVICE : ", device)

parser = argparse.ArgumentParser(description="")
parser.add_argument("--dataset", type=str, default="checker", help="dataset")
parser.add_argument("--corruption", type=str, default="gaussian_noise", help="corruption")
parser.add_argument("--corruption_levels", type=float, nargs='+', help="corruption level")
parser.add_argument("--fc_width", type=int, default=256, help="width of the feedforward network")
parser.add_argument("--fc_depth", type=int, default=3, help="depth of the feedforward network")
parser.add_argument("--train_steps", type=int, default=20000, help="number of channels in model")
parser.add_argument("--batch_size", type=int, default=4000, help="batch size")
parser.add_argument("--learning_rate", type=float, default=5e-4, help="learning rate")
parser.add_argument("--prefix", type=str, default='', help="prefix for folder name")
parser.add_argument("--suffix", type=str, default='', help="suffix for folder name")
parser.add_argument("--lr_scheduler", action='store_true', help="use scheduler if provided, else not")
parser.add_argument("--clean_data_steps", type=int, default=-1, help="number of clean data steps to use in training")
parser.add_argument("--ode_steps", type=int, default=40, help="ode steps")
parser.add_argument("--save_and_sample_every", type=int, default=1000, help="save and sample every n steps")
parser.add_argument("--model_path", type=str, default='latest', help="which model to load")
parser.add_argument("--resume_count", type=int, default=1, help="continued training count")

# Parse arguments
args = parser.parse_args()
# args = parser.parse_args(['--corruption_levels', '0.4',
#                           '--suffix', 'mixed_noise'])

print(args)
train_num_steps = args.train_steps
save_and_sample_every = args.save_and_sample_every
batch_size = args.batch_size
lr = args.learning_rate
lr_scheduler = args.lr_scheduler

# Parse corruption arguments
corruption = args.corruption # to fix
corruption_levels = args.corruption_levels
if args.corruption == "projection_vec_ds":
    assert args.dataset == "manifold_ds", "For projection_vec_ds, dataset should be manifold_ds"
    dataset_path = f"/mnt/home/jhan/diffusion-priors/experiments/manifold/manifold_dataset_eps{corruption_levels[1]:0.2f}.npz"
    assert os.path.exists(dataset_path), f"Dataset path {dataset_path} does not exist"
    A_dataset = Manifold_A_Dataset(dataset_path)
    dl_A = DataLoader(A_dataset, batch_size = batch_size, shuffle = True, pin_memory = True, num_workers = 1, drop_last = True)
    fwd_func = fwd_maps.corruption_dict[corruption](dl_A)
else:
    try:
        fwd_func = fwd_maps.corruption_dict[corruption](*corruption_levels)
    except Exception as e:
        print("Exception in loading corruption function : ", e)
        sys.exit()
cname = "-".join([f"{i:0.2f}" for i in corruption_levels])
folder = f"{args.dataset}-{corruption}-{cname}"
if args.prefix != "": folder = f"{args.prefix}-{folder}"
if args.suffix != "": folder = f"{folder}-{args.suffix}"
results_folder = f"{BASEPATH}/{folder}/"
os.makedirs(results_folder, exist_ok=True)
print(f"Results will be saved in folder: {results_folder}")
use_latents, latent_dim = fwd_maps.parse_latents(corruption, None)

# Initialize model and train
alpha = 1.0
use_follmer = False
if use_follmer:
    diffusion_coef = corruption_levels[1]
else:
    diffusion_coef = None
deconvolver = DeconvolvingInterpolant(fwd_func, use_latents=use_latents, n_steps=args.ode_steps, alpha=alpha, diffusion_coef=diffusion_coef).to(device)
if use_follmer:
    deconvolver.transport = deconvolver.transport_follmer
    deconvolver.loss_fn = deconvolver.loss_fn_follmer
    deconvolver.loss_fn_cleandata = deconvolver.loss_fn_follmer_cleandata
if args.dataset in ["checker", "moon"]:
    dim_in = 2
    # pass DalaLoader as a dataset, will be checked in the trainer
    dataset = DistributionDataLoader(distribution_dict[args.dataset](device=device), batch_size=batch_size, fwd_func=fwd_func, use_latents=use_latents)
    save_fig_fn = save_fig_checker
    clean_data_valid = dataset.distribution.sample(20000).to(device)
elif args.dataset == 'gmm':
    dim_in = 2
    nmix = 4
    def _compute_mu(i):
        return 5.0 * torch.Tensor([[
                    torch.tensor(i * np.pi / 4).sin(),
                    torch.tensor(i * np.pi / 4).cos()]])
    mus_target = torch.stack([_compute_mu(i) for i in range(nmix)]).squeeze(1)
    var_target = torch.stack([torch.tensor([0.7, 0.7]) for i in range(nmix)])
    distribution = distribution_dict[args.dataset](mus_target, var_target, device=device, ndim=dim_in)
    dataset = DistributionDataLoader(distribution, batch_size=batch_size, fwd_func=fwd_func, use_latents=use_latents)
    save_fig_fn = lambda idx, clean, corrupted, generated, results_folder: save_fig_checker(idx, clean, corrupted, generated, results_folder, deconvolver.push_fwd)
    clean_data_valid = dataset.distribution.sample(10000).to(device)
elif args.dataset == "manifold_ds":
    dim_in = 5
    dataset_path = f"/mnt/home/jhan/diffusion-priors/experiments/manifold/manifold_dataset_eps{corruption_levels[1]:0.2f}.npz"
    assert os.path.exists(dataset_path), f"Dataset path {dataset_path} does not exist"
    dataset = ManifoldDataset(dataset_path, epsilon=corruption_levels[1])
    # dl = infinite_dataloader(DataLoader(dataset, batch_size = batch_size, shuffle = True, pin_memory = True, num_workers = 0, drop_last = True))
    save_fig_fn = save_fig_manifold
    clean_data_valid = dataset.x_data.to(device)
else:
    raise ValueError(f"Unknown dataset: {args.dataset}")
corrupted_valid, latents_valid = deconvolver.push_fwd(clean_data_valid, return_latents=True)
latents_valid = latents_valid if use_latents else None
if args.corruption.startswith("projection") and use_latents:
    latent_dim = dim_in * int(args.corruption_levels[0])
else:
    latent_dim = None
if args.corruption == "projection_coeff" and dim_in == int(args.corruption_levels[0]):
    corrupted_valid_plot = torch.linalg.solve(latents_valid, corrupted_valid)
else:
    corrupted_valid_plot = corrupted_valid
valid_data_plot = (clean_data_valid, corrupted_valid_plot, latents_valid)

# to update architecture
# b =  SimpleFeedForward(dim_in, [args.fc_width]*args.fc_depth, latent_dim=latent_dim, use_follmer=use_follmer).to(device)
b =  FeedForwardwithEMB(dim_in, 64, [args.fc_width]*args.fc_depth, latent_dim=latent_dim, use_follmer=use_follmer).to(device)
print("Parameter count : ", count_parameters(b))

trainer = TrainerMLP(model=b,
        deconvolver=deconvolver,
        dataset = dataset,
        train_batch_size = batch_size,
        gradient_accumulate_every = 1,
        train_lr = lr,
        lr_scheduler = lr_scheduler,
        train_num_steps = train_num_steps,
        save_and_sample_every= save_and_sample_every,
        results_folder=results_folder,
        clean_data_steps=args.clean_data_steps,
        save_fig_fn=save_fig_fn,
        valid_data_plot=valid_data_plot,
        )

losses = trainer.train()