"""
The board brain: a Transformer that reads the WHOLE arena — every unit of both sides (card, place, life, flying,
building, just deployed), every spell in the air, the 6 towers' life, both elixirs, the time and our hand — and
says what a strong player does now: play or wait, which card, which tile.
Trained on 252k real games replayed card by card in royale.sim.Arena (scripts/build_royale_board.py), then on the
bot's own battles (royale.selfplay). The same inputs at play time come from the eyes (royale.eyes + royale.health).
"""
NB = 24                     # arena tokens (units / spells), the nearest to our side first
TOK = 8                     # mine, x, y, life, air, building, fresh, age (seconds since played / 15)
GLOB = 11                   # time, double, overtime, my elixir, their elixir, 6 towers
N_HAND = 4
N_TILE = 18 * 32
D = 64


def build(V):
    import torch, torch.nn as nn

    class BoardNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(V, D)
            self.tok = nn.Linear(TOK, D)
            self.glob = nn.Linear(GLOB, D)
            layer = nn.TransformerEncoderLayer(D, 4, 128, dropout=0.0, batch_first=True)
            self.enc = nn.TransformerEncoder(layer, 3, enable_nested_tensor=False)
            self.play = nn.Linear(D, 1)
            self.card = nn.Linear(D, V)
            self.tile = nn.Sequential(nn.Linear(2 * D, 256), nn.ReLU(), nn.Linear(256, N_TILE))

        def forward(self, glob, tok, tokid, hand, cand):
            cls = (self.glob(glob) + self.emb(hand).sum(1)).unsqueeze(1)          # the moment + our hand
            x = self.tok(tok) + self.emb(tokid)                                    # every unit / spell
            h = self.enc(torch.cat([cls, x], 1))[:, 0]
            return self.play(h)[:, 0], self.card(h), self.tile(torch.cat([h, self.emb(cand)], 1))
    return BoardNet()


def export(m, path):
    import torch
    m.eval()
    ex = (torch.zeros(1, GLOB), torch.zeros(1, NB, TOK), torch.zeros(1, NB, dtype=torch.int64),
          torch.zeros(1, N_HAND, dtype=torch.int64), torch.zeros(1, dtype=torch.int64))
    torch.onnx.export(m, ex, str(path), input_names=["glob", "tok", "tokid", "hand", "cand"],
                      output_names=["play", "card", "tile"],
                      dynamic_axes={k: {0: "b"} for k in ("glob", "tok", "tokid", "hand", "cand")},
                      opset_version=17, dynamo=False)


def save_weights(m, path):
    import numpy as np
    np.savez_compressed(str(path), **{k: v.detach().cpu().numpy() for k, v in m.state_dict().items()})


def load(path_npz, V):
    import numpy as np, torch
    m = build(V)
    w = np.load(str(path_npz))
    m.load_state_dict({k: torch.from_numpy(w[k].copy()) for k in m.state_dict()})
    return m


def tokens(board, vocab, key):
    """board: [(mine, card, x, y, life, air, building, fresh, age)] -> (NB x TOK floats, NB ids), our half first."""
    rows = sorted(board, key=lambda b: b[3])[:NB]
    tok, ids = [], []
    for mine, c, x, y, life, air, bld, fresh, age in rows:
        tok.append([1.0 if mine else -1.0, x / 17.0, y / 31.0, float(life), float(air), float(bld), float(fresh),
                    min(1.0, max(0.0, float(age)) / 15.0)])
        ids.append(vocab.get(key(c), 1))
    while len(tok) < NB:
        tok.append([0.0] * TOK); ids.append(0)
    return tok, ids
