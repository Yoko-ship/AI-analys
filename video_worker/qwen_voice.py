"""Batch synthesis with the locally approved Qwen Base voice prompt."""
import hashlib
import json
import os
from pathlib import Path
import sys


def main(config_path, job_dir):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    folder = Path(job_dir)
    plan = json.loads((folder / "storyboard.json").read_text(encoding="utf-8"))
    voice = Path(config["voice_directory"])
    info = json.loads((voice / "voice-prompt.json").read_text(encoding="utf-8"))
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if sha(voice / "voice-prompt.pt") != info["prompt_sha256"] or sha(voice / "reference.wav") != info["reference_sha256"]:
        raise ValueError("The saved voice prompt or reference changed")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem
    if not torch.cuda.is_available():
        raise RuntimeError("The approved local voice needs its CUDA device")
    torch.set_num_threads(4)
    model = Qwen3TTSModel.from_pretrained(config["qwen_model"], device_map="cuda:0", dtype=torch.bfloat16,
                                        attn_implementation="sdpa", local_files_only=True)
    prompt = [VoiceClonePromptItem(**item) for item in torch.load(voice / "voice-prompt.pt", map_location="cpu", weights_only=True)]
    for index, scene in enumerate(plan["scenes"]):
        text = scene["narration"].replace("UZStock", "УзстОк").replace("Узбекистан", "УзбекистАн")
        torch.manual_seed(2311 + index); torch.cuda.manual_seed_all(2311 + index)
        with torch.inference_mode():
            waves, rate = model.generate_voice_clone(text=text, language="Russian", voice_clone_prompt=prompt,
                non_streaming_mode=True, temperature=.9, top_p=.95, repetition_penalty=1.05, max_new_tokens=1500)
        wave = np.asarray(waves[0], dtype=np.float32)
        if not wave.size or not np.isfinite(wave).all() or np.abs(wave).max() < 1e-5:
            raise ValueError("Empty or invalid narration")
        peak = float(np.abs(wave).max())
        if peak > .98:
            wave *= .98 / peak
        sf.write(str(folder / f"voice-{index}.wav"), wave, rate, subtype="PCM_16")
        print(f"Narration scene {index + 1} saved", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
