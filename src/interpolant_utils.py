import torch
import matplotlib.pyplot as plt
from utils import grab

class VelocityField(torch.nn.Module):

    def __init__(self, model, use_compile=False):
        super().__init__()
        self.model = model
        self.use_compile = use_compile

        if self.use_compile:
            self.forward = torch.compile(self.forward)

    def forward(self, x, t, latents=None):
        return self.model(x, t, latents=latents)


class DeconvolvingInterpolant(torch.nn.Module):

    def __init__(self, push_fwd, use_latents=False, n_steps=80, alpha=1.0, resamples=1):
        super().__init__()
        self.push_fwd = push_fwd
        self.n_steps = n_steps
        self.delta_t = 1 / self.n_steps
        self.use_latents = use_latents
        self.alpha = alpha
        self.resamples = resamples
        if use_latents:
            print("Using latents for deonvolving")

    # def loss_fn(self, b, x, latent=None):

    #     x0 = self.transport(b, x, latent=latent)
    #     x1, latent1 = self.push_fwd(x0, return_latents=True)
    #     latent1 = latent1 if self.use_latents else None
    #     t = torch.rand(x.shape[0]).to(x.device)
    #     new_shape = [-1] + [1] * (x.ndim - 1)
    #     t = t.reshape(new_shape)
    #     It = (1-t)*x0 + t*x1
    #     b_true = x1 - x0
    #     bt   = b(It, torch.squeeze(t), latent1)
    #     loss = torch.mean((bt - b_true)**2)
    #     return loss

    def loss_fn(self, b, x, latent=None):

        x0 = self.transport(b, x, latent=latent)
        batch_size = x.shape[0]
        loss = 0.
        for i in range(self.resamples):
            x1, latent1 = self.push_fwd(x0, return_latents=True)
            latent1 = latent1 if self.use_latents else None
            # pick data with probabability 1-alpha
            raw_mask = torch.bernoulli(torch.full((batch_size,), self.alpha)).to(x.device)
            mask = raw_mask.view(batch_size, *([1] * (x.ndim - 1)))
            x1 = x1 * mask + x * (1 - mask)
            if latent1 is not None:
                mask = raw_mask.view(batch_size, *([1] * (latent1.ndim - 1)))
                latent1 = latent1 * mask + latent * (1 - mask)
            # proceed as before
            t = torch.rand(x.shape[0]).to(x.device)
            new_shape = [-1] + [1] * (x.ndim - 1)
            t = t.reshape(new_shape)
            It = (1-t)*x0 + t*x1
            b_true = x1 - x0
            bt   = b(It, torch.squeeze(t), latent1)
            loss += torch.mean((bt - b_true)**2)
        return loss / self.resamples


    def transport(self, b, x, latent=None, return_trajectory=False):

        traj = [x]
        with torch.no_grad():
            Xt_prev = x*1.
            for i in range(1, self.n_steps+1):
                ti = (torch.ones(x.shape[0]) - (i-1) *self.delta_t).to(x.device)
                Xt_prev -= b(Xt_prev, ti, latent) * self.delta_t
                if return_trajectory:
                    traj.append(Xt_prev)
            Xt_final = Xt_prev

        if return_trajectory:
            return traj
        else:
            return Xt_final


def save_fig(idx, image, corrupted, clean, results_folder, epsilon=""):
    to_show = [image, corrupted, clean]

    fig, axar = plt.subplots(len(to_show), 8, figsize=(8, 3), sharex=True, sharey=True)
    vmax, vmin = image.max()*1.1, image.min()*0.5
    for i in range(len(to_show)):
        for j in range(8):
            ax = axar[i, j]
            im = ax.imshow(grab(to_show[i][j]).transpose(1, 2, 0), vmax=vmax, vmin=vmin)
    axar[0, 0].set_ylabel('Original\nImage')
    axar[1, 0].set_ylabel(f'Corrupted\n$\sigma ${epsilon}')
    axar[2, 0].set_ylabel(f'Clean')
    for axis in axar.flatten():
        axis.set_xticks([])
        axis.set_yticks([])
    plt.subplots_adjust(wspace=0.0, hspace=0.0)  # Reduce spacing
    # plt.tight_layout()
    plt.savefig(f'{results_folder}/denoising_{idx}.png', dpi=300)
    plt.close()


def save_fig_checker(idx, clean, corrupted, generated, results_folder, epsilon=""):
    c = '#62508f' # plot color
    fig, axes = plt.subplots(1,3, figsize=(12, 4))

    axes[0].scatter(clean[:,0], clean[:,1], alpha = 0.03, c = c)
    axes[0].set_title(r"Clean samples", fontsize = 18)
    axes[0].set_xlim(-6,6), axes[0].set_ylim(-6,6)
    axes[0].set_xticks([-4,0,4]), axes[0].set_yticks([-4,0,4]);

    axes[1].scatter(corrupted[:,0], corrupted[:,1], alpha = 0.03, c = c)
    axes[1].set_title(r"Corrupted samples", fontsize = 18)
    axes[1].set_xlim(-6,6), axes[2].set_ylim(-6,6)
    axes[1].set_xticks([-4,0,4]), axes[2].set_yticks([]);

    axes[2].scatter(generated[:,0], generated[:,1], alpha = 0.03, c = c)
    axes[2].set_title(r"Generated samples ", fontsize = 18)
    axes[2].set_xlim(-6,6), axes[1].set_ylim(-6,6)
    axes[2].set_xticks([-4,0,4]), axes[1].set_yticks([]);

    plt.subplots_adjust(wspace=0.0, hspace=0.0)  # Reduce spacing
    # plt.tight_layout()
    plt.savefig(f'{results_folder}/denoising_{idx}.png', dpi=300)
    plt.close()
