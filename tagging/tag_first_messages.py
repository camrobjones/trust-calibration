"""Causal probe A: tag TRUNCATED transcripts — the target's opener plus the
persuader's FIRST message only — for all disagreement-trial conversations in
the canonical analysis sample (LLM + human persuaders).

A strategy present in the persuader's opening move cannot be a reaction to
target resistance later in the conversation, so first-message tags give
temporal precedence for the strategy -> success models.

Same tagger as everything else (gpt-5.5, reasoning=high, the original prompt via
retag_untagged imports). Output: retagged/first_message_ratings.csv (15
aggregated categories; persuader categories are the meaningful ones).
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from retag_untagged import (AGG_MAP, OUT_DIR, RAW_COLS, TAGS_DIR,  # noqa: E402
                            aggregate, tag_one, validate_aggregation)
from prompt_for_final_tagging import prompt_column_map  # noqa: E402
from tagger_utils import TagConfig  # noqa: E402

DATA = HERE.parent / "conversation" / "data"
STATS = HERE.parent / "conversation" / "analysis" / "osf" / "stats"
CHECKPOINT = OUT_DIR / "first_message_checkpoint.jsonl"


def build_input():
    """Disagreement-trial conversations from the canonical samples, truncated
    to [target opener ... first persuader message]."""
    trials = pd.concat([pd.read_csv(STATS / f"e{i}_trials.csv") for i in (1, 2, 3, 4)])
    trials = trials[(trials.hint_condition == "Conversation")
                    & (trials.participant_persuader_disagree)]
    conv = pd.read_csv(DATA / "conversation_Conversation.csv")
    m = trials.merge(conv[["id", "participant_id", "question_id", "trial_index",
                           "persuader_answer"]].rename(columns={"id": "conversation_id"}),
                     on=["participant_id", "question_id", "trial_index"], how="left")
    assert len(m) == len(trials)

    questions = pd.read_csv(DATA / "conversation_Question.csv")
    m = m.merge(questions[["id", "question", "answer1", "answer2"]]
                .rename(columns={"id": "question_id"}), on="question_id", how="left")
    m["persuader_answer"] = m.apply(
        lambda r: r.answer1 if r.persuader_answer == "answer1" else r.answer2, axis=1)

    msgs = pd.read_csv(DATA / "conversation_Message.csv")
    msgs = msgs[msgs.conversation_id.isin(m.conversation_id)].copy()
    msgs = msgs.sort_values(["conversation_id", "timestamp", "id"])

    # keep messages up to and including the FIRST persuader ("P") message
    def truncate(g):
        p_idx = (g.sender_role == "P").to_numpy().nonzero()[0]
        if len(p_idx) == 0:
            return g.iloc[0:0]  # no persuader message -> nothing to tag
        return g.iloc[: p_idx[0] + 1]

    trunc = msgs.groupby("conversation_id", group_keys=False).apply(truncate)
    out = trunc.merge(m[["conversation_id", "question", "answer1", "answer2",
                         "persuader_answer"]], on="conversation_id", how="left")
    out = out.rename(columns={"id": "message_id"})
    return out[["conversation_id", "message_id", "sender_role", "content",
                "question", "answer1", "answer2", "persuader_answer"]]


def main():
    validate_aggregation()
    cfg = TagConfig(reasoning="high")
    df = build_input()
    convos = sorted(df.conversation_id.unique().tolist())
    print(f"{len(convos)} disagreement-trial conversations, truncated to first persuader message")
    print(f"median messages per truncated convo: {df.groupby('conversation_id').size().median()}")

    done = {}
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text().splitlines():
            rec = json.loads(line)
            done[rec["conversation_id"]] = rec["result"]
        print(f"resuming: {len(done)} in checkpoint")
    todo = [c for c in convos if c not in done]
    if "--smoke" in sys.argv:
        todo = todo[:2]

    with CHECKPOINT.open("a") as ckpt, ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(tag_one, df, c, cfg): c for c in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            c = futures[fut]
            result = fut.result()
            done[c] = result
            ckpt.write(json.dumps({"conversation_id": c, "result": result}) + "\n")
            ckpt.flush()
            if i % 25 == 0 or i == len(todo):
                errs = sum(1 for r in done.values() if r.get("status") == "error")
                print(f"{i}/{len(todo)} tagged ({errs} errors)", flush=True)

    if "--smoke" in sys.argv:
        for c in todo:
            print(c, json.dumps(done[c]))
        return

    strategy_cols = [c for c in RAW_COLS if c not in ("conversation_id", "rater_initials", "status")]
    rows = []
    for c in convos:
        out = done.get(c)
        if out is None:
            continue
        row = {"conversation_id": c, "rater_initials": cfg.label + "_firstmsg",
               "status": out.get("status", "error")}
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
    raw_df.to_csv(OUT_DIR / "first_message_ratings_raw.csv", index=False)
    good = raw_df[raw_df.status == "good"].copy()
    agg = aggregate(good)
    agg.columns = ["conversation_id"] + ["fm_" + c for c in agg.columns[1:]]
    agg.to_csv(OUT_DIR / "first_message_ratings.csv", index=False)
    print(f"wrote {OUT_DIR}/first_message_ratings.csv ({len(good)} good rows, "
          f"{(raw_df.status == 'error').sum()} errors)")


if __name__ == "__main__":
    main()
