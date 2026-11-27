"""Train a fresh policy against past copies in the local Royale simulator."""
import argparse
import json
import multiprocessing
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
XBOW_DECK = "evo:archers,knight,evo:tesla,x-bow,skeletons,electro spirit,fireball,the log"


def evaluate(engine, deck, candidate, initial, pairs, seed):
    from royale.engine_ai import _duel, _load

    challenger, baseline = _load(candidate), _load(initial)
    matches = []
    heuristic_matches = []
    for offset in range(pairs):
        match_seed = seed + offset
        bottom = _duel(engine, deck, challenger, baseline, seed=match_seed)
        top = 1.0 - _duel(engine, deck, baseline, challenger, seed=match_seed)
        matches.append({"seed": match_seed, "candidate_bottom": bottom, "candidate_top": top})
        heuristic_matches.append({
            "seed": match_seed,
            "candidate": _duel(engine, deck, challenger, None, seed=match_seed),
            "initial": _duel(engine, deck, baseline, None, seed=match_seed),
        })
    scores = [match[side] for match in matches for side in ("candidate_bottom", "candidate_top")]
    return {
        "opponent": "frozen untrained initial policy",
        "wins": scores.count(1.0),
        "draws": scores.count(0.5),
        "losses": scores.count(0.0),
        "score": sum(scores) / len(scores),
        "pairs": matches,
        "native_heuristic": {
            "candidate_score": sum(match["candidate"] for match in heuristic_matches) / pairs,
            "initial_score": sum(match["initial"] for match in heuristic_matches) / pairs,
            "matches": heuristic_matches,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True, help="New directory for all run artifacts")
    parser.add_argument("--deck", default=XBOW_DECK, help="Eight engine card names or IDs, separated by commas")
    parser.add_argument("--updates", type=int, default=20)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--snapshot-every", type=int, default=5)
    parser.add_argument("--eval-pairs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7013)
    args = parser.parse_args()
    if min(args.updates, args.workers, args.snapshot_every, args.eval_pairs) < 1:
        parser.error("updates, workers, snapshot cadence and evaluation pairs must be positive")
    if not 0 <= args.seed < 2**32 - args.eval_pairs - 1:
        parser.error("seed and evaluation seeds must fit in 32 bits")

    sys.path.insert(0, str(ROOT / "src"))
    from royale import engine

    module = engine.module()
    if module is None:
        parser.error("the native simulator is unavailable for this Python interpreter")
    if not engine.selftest():
        parser.error("the native simulator failed its self-test")

    os.environ["CLASH_DECK"] = args.deck
    os.environ["CLASH_ADVISOR_COVERAGE_COEF"] = "0"
    os.environ["CLASH_HUMAN_PRIOR_COEF"] = "0"
    sys.path.insert(0, str(ROOT / "third_party" / "clash_royale_env"))
    import python_ai
    from python_ai.deck import DEFAULT_DECK
    from python_ai.rl.abilities import ability_engine_slots

    if ability_engine_slots(DEFAULT_DECK):
        parser.error("this evaluation only supports decks without active ability slots")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    # The trainer resolves replay and historical paths when its modules load.
    python_ai.REPO_ROOT = str(out_dir)

    import gymnasium as gym
    import torch
    from python_ai.envs import selfplay_env
    from python_ai.rl.checkpointing import atomic_save
    from python_ai.rl.config import PPOConfig
    from python_ai.rl.seeding import worker_seeds
    from python_ai.trainers.train_selfplay import Phase2Trainer

    torch.set_num_threads(2)
    initial = out_dir / "initial.pth"
    candidate = out_dir / "candidate.pth"

    class ScratchTrainer(Phase2Trainer):
        weight_path = str(candidate)
        log_dir = str(out_dir / "tensorboard")
        completed_updates = 0

        def build_envs(self):
            seeds = worker_seeds(self.cfg.seed, self.cfg.num_envs)
            return gym.vector.AsyncVectorEnv([
                selfplay_env.make_env(seed=seed, scenarios_enabled=False) for seed in seeds
            ])

        def load_checkpoint(self):
            # Save the random policy before the first reset, so every opponent
            # comes from this run, including during the first rollout.
            atomic_save(self.net.state_dict(), str(initial))
            self.historical_pool = [str(initial)]
            self._refresh_pool()
            return False

        def _refresh_pool(self, initial=False):
            self.envs.call("refresh_pfsp_pool", self.historical_pool)

        def on_after_update(self, stats):
            self.completed_updates += 1
            if self.completed_updates % args.snapshot_every == 0:
                snapshot = out_dir / "historical_checkpoints" / f"update-{self.completed_updates}.pth"
                atomic_save(self.net.state_dict(), str(snapshot))
                self.historical_pool = [str(initial), *self.historical_pool[1:][-6:], str(snapshot)]
                self._refresh_pool()

        def should_stop(self):
            return self.completed_updates >= args.updates

        def on_finish(self):
            self.save_checkpoint()

    config = PPOConfig(num_envs=args.workers, seed=args.seed)
    trainer = ScratchTrainer(config)
    try:
        trainer.run()
    finally:
        if trainer.envs is not None:
            trainer.envs.close()
        if trainer.writer is not None:
            trainer.writer.close()
    checkpoint = torch.load(candidate, map_location="cpu", weights_only=True)
    if not all(torch.isfinite(tensor).all().item() for tensor in checkpoint["model"].values()):
        raise RuntimeError("Candidate weights contain non-finite values")
    benchmark = evaluate(module, DEFAULT_DECK, candidate, initial, args.eval_pairs, 2**32 - args.eval_pairs)
    report = {
        "simulator": "CoC_Bot native ClashRoyaleEnv",
        "deck_spec": args.deck,
        "deck_ids": DEFAULT_DECK,
        "training_seed": args.seed,
        "device": str(trainer.device),
        "workers": config.num_envs,
        "training_updates": trainer.completed_updates,
        "completed_training_matches": trainer.episodes_completed,
        "evaluation": benchmark,
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Evaluation: {benchmark['wins']} wins, {benchmark['draws']} draws, "
          f"{benchmark['losses']} losses. Report: {report_path}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
