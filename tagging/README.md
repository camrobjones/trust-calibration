# LLM tagging

Code that produced the strategy tags in `data/tags/`. It is here for transparency. **Reproducing the
paper does not require running it**, because `run_all.R` starts from the stored tags.

| File | Purpose |
|---|---|
| `prompt_for_final_tagging.py` | The final tagging prompt |
| `tagger_runner_batch.py`, `tagger_utils.py` | Batch runner and parsing/validation |
| `retag_untagged.py` | Tags the 216 conversations missed by the first run, with the same prompt and model |
| `tag_first_messages.py` | Tags transcripts cut after the persuader's first message |
| `tag_position_compliance.py` | Codes whether the persuader argued the assigned position |
| `CODEBOOK.md` | Definitions of all strategies |
| `irr_report.pdf` | Reliability write-up; `analysis/irr.py` recomputes its tables |

Re-running needs an OpenAI API key and access to the model used (GPT-5.5, high reasoning effort), and
a re-run will not match exactly: LLM output is not deterministic, these scripts expect input files
that were derived from the original transcripts, and the released transcripts contain a few masked
words (see `data/README.md`).
