# Model Sources

No language-model weights are included. The frozen result files contain candidate scores and decisions generated during the reported research run.

| Local alias | Upstream model ID | Recorded role | Upstream license |
| --- | --- | --- | --- |
| `qwen2.5-3b` | [Qwen/Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) | Two-candidate scoring | Qwen Research License; non-commercial research/evaluation unless separately licensed |
| `smollm2-1.7b` | [HuggingFaceTB/SmolLM2-1.7B-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct) | Two-candidate scoring | Apache-2.0 |
| `phi3.5-mini` | [microsoft/Phi-3.5-mini-instruct](https://huggingface.co/microsoft/Phi-3.5-mini-instruct) | Two-candidate scoring | MIT |

The model IDs, random seed, confidence threshold, bootstrap count, and hashes of core experiment files are stored in `outputs/lab_evidence_benchmark_v2/RUN_CONTRACT.json`.

## Reproduction limit

The original run contract did not store immutable Hugging Face commit revisions for the three model repositories. A future download under the same model ID may therefore differ from the exact files used in the reported run. The packaged candidate scores are the authoritative retained evidence for the paper-facing analysis.

Before downloading or running a model:

1. Read and accept the current upstream model license.
2. Confirm that the intended use is permitted, especially for Qwen2.5-3B-Instruct.
3. Install a PyTorch build that matches the local hardware and CUDA runtime.
4. Use a new output directory; reported score files are immutable evidence.

The repository MIT License does not grant rights to any model, tokenizer, model code, or weight file.
