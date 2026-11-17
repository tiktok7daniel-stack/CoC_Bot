"""
Train the bot's screen model on the labelled pictures of the learning repo (run by Claude after marking pictures).
  python scripts/build_screen_model.py <learning repo folder>
Writes <repo>/knowledge/model.json (fetched by the bot) and assets/screen_model.json (shipped with the bot),
and prints the leave-one-out accuracy.
"""
import json, os, sys, time
import cv2, numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import screen_model as sm


def main(repo):
    it = json.load(open(os.path.join(repo, "knowledge", "status.json"), encoding="utf-8"))["items"]
    sc = json.load(open(os.path.join(repo, "knowledge", "screens.json"), encoding="utf-8"))
    def path(k):
        if k.startswith("captures/"): return os.path.join(repo, k + ".jpg")
        for dp, _, fs in os.walk(os.path.join(repo, "inbox")):
            if k + ".jpg" in fs: return os.path.join(dp, k + ".jpg")
    pairs = []
    for k, v in it.items():
        p = path(k) if v.get("rule") else None
        if p and os.path.exists(p): pairs.append((v["rule"], cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)))
    right = wrong = unsure = 0
    for i in range(len(pairs)):
        m = sm.build(pairs[:i] + pairs[i + 1:])
        sm._M.update(t=time.time(), ex=np.array([sm._unpack(x["v"]) for x in m["items"]]), labels=[x["rule"] for x in m["items"]])
        lab, d = sm._classify(pairs[i][1])
        if lab is None: unsure += 1
        elif lab == pairs[i][0]: right += 1
        else:
            wrong += 1
            print(f"  wrong: {pairs[i][0]} -> {lab} ({d:.3f})")
    print(f"pictures it never saw: right {right}, wrong {wrong}, not sure {unsure} (of {len(pairs)})")
    model = sm.build(pairs, {r["id"]: r.get("title_ar", r["id"]) for r in sc.get("screens", [])})
    for out in (os.path.join(repo, "knowledge", "model.json"), os.path.join(ROOT, "assets", "screen_model.json")):
        json.dump(model, open(out, "w"))
    # the deep brain (DINOv2): the same pictures as examples (the network downloads itself the first time)
    import screen_cnn
    screen_cnn.download()
    if screen_cnn._S["dl"] is not None: screen_cnn._S["dl"].join()
    screen_cnn._S["tried"] = 0.0
    if screen_cnn.ready():
        bank = screen_cnn.build(pairs)
        E = np.array([screen_cnn._unpack(x["v"]) for x in bank["items"]])
        L = [x["rule"] for x in bank["items"]]
        ok = 0
        for i in range(len(L)):
            sim = E @ E[i]
            sim[i] = -9
            ok += L[int(np.argmax(sim))] == L[i]
        print(f"deep brain (DINOv2): pictures it never saw: right {ok} of {len(L)}")
        for out in (os.path.join(repo, "knowledge", "model_cnn.json"), os.path.join(ROOT, "assets", "screen_cnn.json")):
            json.dump(bank, open(out, "w"))
    else:
        print("deep brain: network not available —", screen_cnn._S["error"])
    print(f"model: {len(model['items'])} pictures, {len(set(r for r, _ in pairs))} kinds of screen")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
