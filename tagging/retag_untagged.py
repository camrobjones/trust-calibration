"""Run the original final tagger (GPT 5.5, reasoning=high) on the 221 canonical E3
conversation trials (+ any other convos) missing from final_ratings.csv.

Input:  untagged_conversations.csv (written by qualitative_tags.Rmd; same format
        as llm_conversations.csv, the original input).
Output: retagged/final_ratings_raw_addendum.csv  (26 raw strategies, matches
        final_ratings_raw.csv column layout)
        retagged/final_ratings_addendum.csv      (15 aggregated categories,
        matches final_ratings.csv layout)

Fidelity: imports PROMPT_ALL, prompt_column_map, format_conversation, and
parse_and_validate from the original repo unmodified; same model + reasoning setting
(synchronous Responses API instead of the batch API — transport only).
The 26->15 OR-aggregation is validated by exactly reconstructing the original
final_ratings.csv from final_ratings_raw.csv before tagging anything.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "persuasion_trust_tagger"))

# tagger_utils builds an OpenAI client from OPENAI_API_KEY_SECRET at import time
os.environ.setdefault("OPENAI_API_KEY_SECRET", os.environ["OPENAI_API_KEY"])
from prompt_for_final_tagging import PROMPT_ALL, prompt_column_map  # noqa: E402
from tagger_utils import TagConfig, client, format_conversation, parse_and_validate  # noqa: E402

TAGS_DIR = HERE / "drive-download-20260814T075127Z-1-001"
OUT_DIR = HERE / "retagged"
OUT_DIR.mkdir(exist_ok=True)
CHECKPOINT = OUT_DIR / "responses_checkpoint.jsonl"

RAW_COLS = pd.read_csv(TAGS_DIR / "final_ratings_raw.csv", nrows=0).columns.tolist()
FINAL_COLS = pd.read_csv(TAGS_DIR / "final_ratings.csv", nrows=0).columns.tolist()

AGG_MAP = {
    "deception_false": ["deception_faulty_math", "deception_false_statements",
                        "deception_faulty_reasoning", "deception_false_claim"],
    "deception_misleading": ["deception_misleading_facts", "deception_misleading_exhortation",
                             "deception_misdirection", "deception_misleading_omission",
                             "deception_misapply_principle"],
    "deception_provably_false": ["deception_provably_false"],
    "persuader_acknowledge": ["persuader_acknowledge"],
    "persuader_analogy": ["persuader_analogy"],
    "persuader_authority": ["persuader_authority"],
    "persuader_flattery": ["persuader_flattery"],
    "persuader_gave_up": ["persuader_gave_up"],
    "persuader_math": ["persuader_math", "persuader_math_reason"],
    "persuader_personal": ["persuader_personal"],
    "persuader_principle": ["persuader_principle"],
    "target_disagreement": ["target_disagreement"],
    "target_probe": ["target_cross_examination", "target_evidence_request",
                     "target_clarification", "target_conditional_challenge"],
    "target_question": ["target_question"],
    "target_statement": ["target_statement"],
}


def aggregate(raw_df):
    out = pd.DataFrame({"conversation_id": raw_df["conversation_id"]})
    for cat, cols in AGG_MAP.items():
        out[cat] = raw_df[cols].max(axis=1).astype(int)
    return out[FINAL_COLS]


def validate_aggregation():
    raw = pd.read_csv(TAGS_DIR / "final_ratings_raw.csv")
    final = pd.read_csv(TAGS_DIR / "final_ratings.csv")
    recon = aggregate(raw).sort_values("conversation_id").reset_index(drop=True)
    final = final.sort_values("conversation_id").reset_index(drop=True)
    assert recon.equals(final), "Aggregation rule does NOT reproduce the original final_ratings.csv"
    print(f"aggregation rule validated: reconstructed all {len(final)} rows of final_ratings.csv exactly")


def tag_one(df, conversation_id, cfg, max_retries=3):
    for attempt in range(max_retries):
        try:
            kwargs = dict(
                model=cfg.mdl,
                input=[{"role": "system", "content": PROMPT_ALL},
                       {"role": "user", "content": format_conversation(df, conversation_id)}],
            )
            if cfg.reasoning:
                kwargs["reasoning"] = {"effort": cfg.reasoning}
            resp = client.responses.create(**kwargs)
            return parse_and_validate(resp.output_text)
        except Exception as e:  # rate limits / transient API errors
            if attempt == max_retries - 1:
                print(f"convo {conversation_id}: giving up after {max_retries} tries ({e})")
                return {"status": "error", "provably_false": False,
                        "target_strategies": [], "persuader_strategies": [], "deception_strategies": []}
            time.sleep(15 * (attempt + 1))


def main():
    validate_aggregation()

    cfg = TagConfig(reasoning="high")  # gpt-5.5, no temperature, reasoning=high
    print(f"tagger config: model={cfg.mdl} reasoning={cfg.reasoning} label={cfg.label}")

    df = pd.read_csv(HERE / "untagged_conversations.csv")
    df = df.rename(columns={"id": "message_id"})
    convos = sorted(df.conversation_id.unique().tolist())

    already_final = set(pd.read_csv(TAGS_DIR / "final_ratings.csv").conversation_id)
    assert not (set(convos) & already_final), "input overlaps already-tagged conversations"
    print(f"{len(convos)} conversations to tag")

    done = {}
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text().splitlines():
            rec = json.loads(line)
            done[rec["conversation_id"]] = rec["result"]
        print(f"resuming: {len(done)} already in checkpoint")

    todo = [c for c in convos if c not in done]
    smoke = "--smoke" in sys.argv
    if smoke:
        todo = todo[:1]

    with CHECKPOINT.open("a") as ckpt, ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(tag_one, df, c, cfg): c for c in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            c = futures[fut]
            result = fut.result()
            done[c] = result
            ckpt.write(json.dumps({"conversation_id": c, "result": result}) + "\n")
            ckpt.flush()
            if i % 10 == 0 or i == len(todo):
                errs = sum(1 for r in done.values() if r.get("status") == "error")
                print(f"{i}/{len(todo)} tagged ({errs} errors)")

    if smoke:
        print("SMOKE RESULT:", json.dumps(done[todo[0]], indent=2))
        return

    # Build raw dataframe in final_ratings_raw.csv layout
    strategy_cols = [c for c in RAW_COLS if c not in ("conversation_id", "rater_initials", "status")]
    rows = []
    for c in convos:
        out = done[c]
        row = {"conversation_id": c, "rater_initials": cfg.label, "status": out.get("status", "error")}
        tagged = set()
        for key in (out.get("target_strategies", []) + out.get("persuader_strategies", [])
                    + out.get("deception_strategies", [])):
            if key in prompt_column_map:
                tagged.add(prompt_column_map[key])
        if out.get("provably_false"):
            tagged.add("deception_provably_false")
        for col in strategy_cols:
            row[col] = pd.NA if out.get("status") == "error" else int(col in tagged)
        rows.append(row)
    raw_df = pd.DataFrame(rows)[RAW_COLS]

    n_err = (raw_df.status == "error").sum()
    print(f"done: {len(raw_df)} rows, {n_err} errors")

    raw_df.to_csv(OUT_DIR / "final_ratings_raw_addendum.csv", index=False)
    good = raw_df[raw_df.status == "good"].copy()
    aggregate(good).to_csv(OUT_DIR / "final_ratings_addendum.csv", index=False)
    print(f"wrote {OUT_DIR}/final_ratings_raw_addendum.csv and final_ratings_addendum.csv "
          f"({len(good)} good rows)")


if __name__ == "__main__":
    main()
