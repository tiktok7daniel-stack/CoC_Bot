"""The learned brain's network (the same for the first training on 17 M pro plays and for its own learning)."""
N_EN, N_OWN, N_HAND = 6, 4, 4
N_TILE = 18 * 32
EMB = 24


def build(V, n_float):
    import torch, torch.nn as nn

    class Policy(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(V, EMB)
            n_in = n_float + (N_EN + N_OWN) * EMB + EMB
            self.trunk = nn.Sequential(nn.Linear(n_in, 512), nn.ReLU(), nn.Linear(512, 512), nn.ReLU(),
                                       nn.Linear(512, 256), nn.ReLU())
            self.play = nn.Linear(256, 1)
            self.card = nn.Linear(256, V)
            self.tile = nn.Sequential(nn.Linear(256 + EMB, 512), nn.ReLU(), nn.Linear(512, N_TILE))

        def forward(self, x, ids):
            e = self.emb(ids)                     # (B, 15, 24): 10 history, 4 hand cards, the card to place
            k = N_EN + N_OWN
            h = self.trunk(torch.cat([x, e[:, :k].flatten(1), e[:, k:k + N_HAND].sum(1)], 1))
            return self.play(h)[:, 0], self.card(h), self.tile(torch.cat([h, e[:, -1]], 1))
    return Policy()


def from_onnx(path, V, n_float):
    """The network with the weights of an exported ONNX file (the names are the same)."""
    import onnx, torch
    from onnx import numpy_helper
    m = build(V, n_float)
    w = {i.name: torch.from_numpy(numpy_helper.to_array(i).copy()) for i in onnx.load(str(path)).graph.initializer}
    m.load_state_dict({k: w[k] for k in m.state_dict()})
    return m


def export(m, path, n_float):
    import torch
    ex = (torch.zeros(1, n_float), torch.zeros(1, N_EN + N_OWN + N_HAND + 1, dtype=torch.int64))
    torch.onnx.export(m, ex, str(path), input_names=["x", "ids"], output_names=["play", "card", "tile"],
                      dynamic_axes={"x": {0: "b"}, "ids": {0: "b"}}, opset_version=17, dynamo=False)


def save_weights(m, path):
    """The weights as a plain numpy file (no extra package needed to read them back)."""
    import numpy as np
    np.savez_compressed(str(path), **{k: v.detach().cpu().numpy() for k, v in m.state_dict().items()})


def load(path_npz, V, n_float):
    import numpy as np, torch
    m = build(V, n_float)
    w = np.load(str(path_npz))
    m.load_state_dict({k: torch.from_numpy(w[k].copy()) for k in m.state_dict()})
    return m
