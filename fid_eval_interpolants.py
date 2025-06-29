import torch
import sys, os
import json
import argparse
from torch.utils.data import DataLoader, Dataset
from ema_pytorch import EMA
import numpy as np

sys.path.append('./src/')
from networks import ConditionalDhariwalUNet
from custom_datasets import dataset_dict, ImagesOnly, cifar10_inverse_transforms
from interpolant_utils import DeconvolvingInterpolant
import forward_maps as fwd_maps
from fid_evaluation import FIDEvaluation, calculate_frechet_distance
from utils import infinite_dataloader,  num_to_groups, remove_orig_mod_prefix
from tqdm.auto import tqdm


device = 'cuda' if torch.cuda.is_available() else 'cpu'
print("DEVICE : ", device)

# Create an ArgumentParser object
parser = argparse.ArgumentParser(description="")
parser.add_argument("--model", type=str, default="best", help="which model to load")
parser.add_argument("--dataset", type=str, help="dataset")
parser.add_argument("--corruption", type=str, help="corruption")
parser.add_argument("--corruption_levels", type=float, nargs='+', help="corruption level")
parser.add_argument("--channels", type=int, default=64, help="number of channels in model")
parser.add_argument("--n_samples", type=int, default=50_000, help="Samples to evalaute FID")
parser.add_argument("--batch_size", type=int, default=128, help="batch size")
parser.add_argument("--prefix", type=str, default='', help="prefix for folder name")
parser.add_argument("--suffix", type=str, default='', help="suffix for folder name")
parser.add_argument("--subfolder", type=str, default='', help="subfolder for folder name")
parser.add_argument("--gated", action='store_true', help="gated convolution if provided, else not")
parser.add_argument("--ode_steps", type=int, default=80, help="number of steps for ODE sampling")
parser.add_argument("--multiview", action='store_true', help="change corruption every epoch if provided, else not")
parser.add_argument("--max_pos_embedding", type=int, default=2, help="number of resamplings")
args = parser.parse_args()
print(args)
if args.multiview:
    BASEPATH = '/mnt/ceph/users/cmodi/diffusion_guidance/multiview/'
else:
    BASEPATH = '/mnt/ceph/users/cmodi/diffusion_guidance/singleview/'

# Parse arguments
dataset, D, nc = dataset_dict[args.dataset]
dl = infinite_dataloader(DataLoader(ImagesOnly(dataset), 
                                    batch_size = args.batch_size, \
                                    shuffle = True, pin_memory = True, num_workers = 1))
gated = args.gated
if gated: 
    args.suffix = f"{args.suffix}-gated" if args.suffix else "gated"
print(BASEPATH)

# Parse corruption arguments
corruption = args.corruption
corruption_levels = args.corruption_levels
try:
    fwd_func = fwd_maps.corruption_dict[corruption](*corruption_levels)
except Exception as e:
    print("Exception in loading corruption function : ", e)
    sys.exit()
cname = "-".join([f"{i:0.2f}" for i in corruption_levels])
folder = f"{args.dataset}-{corruption}-{cname}"
if args.prefix != "": folder = f"{args.prefix}-{folder}"
if args.suffix != "": folder = f"{folder}-{args.suffix}"
if args.subfolder != "": folder = f"{folder}/{args.subfolder}/"

folder = f"{BASEPATH}/{folder}/"
results_folder = f"{folder}/results"
os.makedirs(results_folder, exist_ok=True)
print(f"Models will be loaded from folder: {folder}")
use_latents, latent_dim = fwd_maps.parse_latents(corruption, D)
if use_latents:
    print("Will use latents of dimension: ", latent_dim)
n = int(args.n_samples/1e3)
save_name = f"{results_folder}/fid_{n}k_{args.ode_steps}steps_{args.model}.json"
print(f"Results will be saved in file: {save_name}")


deconvolver = DeconvolvingInterpolant(fwd_func, use_latents=use_latents, n_steps=args.ode_steps).to(device)
b = ConditionalDhariwalUNet(D, nc, nc, latent_dim=latent_dim, model_channels=args.channels, gated=gated, \
                            max_pos_embedding=args.max_pos_embedding).to(device)
ema_b = EMA(b)
data = torch.load(f'{folder}/model-{args.model}.pt', weights_only=True)
try:
    b.load_state_dict(data['model'])
    ema_b.load_state_dict(data['ema'])
except Exception as e :
    print("Saved compiled model. Trying to load without compilation")
    cleaned_ckpt = remove_orig_mod_prefix(data['model'])
    b.load_state_dict(cleaned_ckpt)
    cleaned_ckpt = remove_orig_mod_prefix(data['ema'])
    ema_b.load_state_dict(cleaned_ckpt)    
b = ema_b.ema_model



fid_scorer = FIDEvaluation(
    batch_size=args.batch_size,
    dl=dl,
    channels=nc,
    accelerator=None, #args.accelerator,
    stats_dir=results_folder,
    device=device,
    num_fid_samples=args.n_samples,
    inception_block_idx=2048
)    
if not fid_scorer.dataset_stats_loaded:
    fid_scorer.load_or_precalc_dataset_stats(force_calc=True)

@torch.inference_mode()
def get_cleaned_samples():
    image = next(dl).to(device)
    corrupted, latents = deconvolver.push_fwd(image, return_latents=True)
    latents = latents if use_latents else None
    clean = deconvolver.transport(b, corrupted, latents)
    return clean

batches = num_to_groups(fid_scorer.n_samples, fid_scorer.batch_size)
stacked_fake_features = []
print(f"Stacking Inception features for {fid_scorer.n_samples} generated samples.")

for batch in tqdm(batches):
    fake_samples = get_cleaned_samples()    
    fake_features = fid_scorer.calculate_inception_features(fake_samples)
    stacked_fake_features.append(fake_features)
stacked_fake_features = torch.cat(stacked_fake_features, dim=0).cpu().numpy()
m1 = np.mean(stacked_fake_features, axis=0)
s1 = np.cov(stacked_fake_features, rowvar=False)
score = calculate_frechet_distance(m1, s1, fid_scorer.m2, fid_scorer.s2)
print(f"FID score of loaded best model : {score}")

to_save = {'FID_best': score}
with open(save_name, 'w') as file:
        json.dump(to_save, file, indent=4)
