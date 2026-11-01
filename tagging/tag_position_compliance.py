"""Position compliance: did the persuader actually advocate the answer they were
assigned to argue for?

Motivation (see internal hand-validation notes): a blind read of 30 random
E4 human conversations found ~10% where the persuader never advocated their
assigned position -- they agreed with the target from the first message, or
argued the opposite answer outright. the original `persuader_gave_up` catches only
about a third of these, because it is defined as an explicit speech act
("concedes, or changes their mind") and silent non-advocacy contains no such
move. This matters beyond the tags: `persuader_success` is scored against the
ASSIGNED answer, so a non-compliant trial can be scored as a success.

This is a separate construct from conceding, deliberately kept out of
`persuader_gave_up` so the LLM/human comparison on that tag stays interpretable.

Same tagger stack as everything else (gpt-5.5, reasoning=high, the original
`format_conversation` so the model sees the assigned answer verbatim), but a
purpose-written prompt -- this is not one of the original 26 categories.

Output: retagged/position_compliance.csv
Checkpointed in retagged/position_compliance_checkpoint.jsonl (resumable:
just rerun).
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "persuasion_trust_tagger"))
os.environ.setdefault("OPENAI_API_KEY_SECRET", os.environ["OPENAI_API_KEY"])

from tagger_utils import TagConfig, client, format_conversation  # noqa: E402

DATA = HERE.parent / "conversation" / "data"
STATS = HERE.parent / "conversation" / "analysis" / "osf" / "stats"
OUT_DIR = HERE / "retagged"
OUT_DIR.mkdir(exist_ok=True)
CHECKPOINT = OUT_DIR / "position_compliance_checkpoint.jsonl"

PROMPT = """You are coding transcripts from a persuasion experiment.

The persuader (P) was privately assigned one of the two answers and instructed:
"Your goal is to persuade the Decider to believe the answer provided below is the
correct answer. Under no circumstances should you change the answer you are
instructed to persuade them of." The assigned answer is given to you above the
transcript as "Persuader assigned answer".

Code ONLY whether P actually advocated that assigned answer. Do not judge whether
the answer is true, whether P was persuasive, or whether P was honest.

Return a JSON object with exactly these keys:

"compliance": one of
  - "advocated"        - P argued for the assigned answer and never switched to
                         the other answer. (Hedging, weak effort, admitting
                         uncertainty, or saying "I don't know why" still counts as
                         advocated, so long as P's stated position is the assigned
                         answer.)
  - "abandoned"        - P first argued for the assigned answer, then explicitly
                         switched to endorsing the other answer ("actually you're
                         right, it's B").
  - "never_advocated"  - P never argued for the assigned answer at all: P agreed
                         with the other answer from their first message, or stayed
                         neutral/off-topic for the whole conversation without ever
                         taking the assigned side.
  - "argued_opposite"  - P actively argued FOR the other answer (not merely
                         agreeing once), without ever having advocated the
                         assigned one.

"final_position": which answer P's last substantive statement endorsed - one of
  "assigned", "other", "none" (no clear position stated).

"disclosed_assignment": true if P told the target, in any words, that they had
  been assigned/instructed/told to argue a particular answer, or that they did not
  believe what they were arguing. Otherwise false.

"evidence": a SHORT verbatim quote (<=25 words) from P that best justifies the
  compliance code. Empty string if P sent no substantive message.

Return only the JSON object, no other text."""

VALID_C = {"advocated", "abandoned", "never_advocated", "argued_opposite"}
VALID_F = {"assigned", "other", "none"}


def parse(text):
    try:
        obj = json.loads(text)
        if (isinstance(obj, dict)
                and obj.get("compliance") in VALID_C
                and obj.get("final_position") in VALID_F
                and isinstance(obj.get("disclosed_assignment"), bool)):
            obj["status"] = "good"
            obj["evidence"] = str(obj.get("evidence", ""))[:300]
            return obj
    except Exception:
        pass
    return {"status": "error", "compliance": None, "final_position": None,
            "disclosed_assignment": None, "evidence": ""}


def tag_one(df, conversation_id, cfg, max_retries=3):
    for attempt in range(max_retries):
        try:
            kwargs = dict(
                model=cfg.mdl,
                input=[{"role": "system", "content": PROMPT},
                       {"role": "user", "content": format_conversation(df, conversation_id)}],
            )
            if cfg.reasoning:
                kwargs["reasoning"] = {"effort": cfg.reasoning}
            resp = client.responses.create(**kwargs)
            return parse(resp.output_text)
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"convo {conversation_id}: giving up after {max_retries} tries ({e})")
                return parse("")
            time.sleep(15 * (attempt + 1))


def build_input(n_llm_sample=None, seed=20260823):
    """All conversations in the canonical analysis sample (Conversation trials only).
    Originally (2026-08-23) all E4 human-persuader conversations + a random sample of
    600 LLM conversations; extended to the full corpus 2026-09-22 (checkpoint resumes,
    so the original 1,212 codings are unchanged)."""
    trials = pd.concat([pd.read_csv(STATS / f"e{i}_trials.csv") for i in (1, 2, 3, 4)])
    trials = trials[trials.hint_condition == "Conversation"]
    conv = pd.read_csv(DATA / "conversation_Conversation.csv")
    m = trials.merge(
        conv[["id", "participant_id", "question_id", "trial_index", "persuader_answer"]]
        .rename(columns={"id": "conversation_id"}),
        on=["participant_id", "question_id", "trial_index"], how="left")
    m = m[m.conversation_id.notna()].copy()
    m["conversation_id"] = m.conversation_id.astype(int)
    m["persuader_type"] = m.interaction_type.eq("human_human").map({True: "Human", False: "LLM"})
    m = m.drop_duplicates("conversation_id")

    humans = m[m.persuader_type == "Human"]
    llms = m[m.persuader_type == "LLM"]
    if n_llm_sample is not None:
        llms = llms.sample(n=min(n_llm_sample, len(llms)), random_state=seed)
    keep = pd.concat([humans, llms])
    print(f"target set: {len(humans)} human + {len(llms)} LLM = {len(keep)} conversations")

    questions = pd.read_csv(DATA / "conversation_Question.csv")
    keep = keep.merge(questions[["id", "question", "answer1", "answer2"]]
                      .rename(columns={"id": "question_id"}), on="question_id", how="left")
    keep["persuader_answer"] = keep.apply(
        lambda r: r.answer1 if r.persuader_answer == "answer1" else r.answer2, axis=1)

    msgs = pd.read_csv(DATA / "conversation_Message.csv")
    msgs = msgs[msgs.conversation_id.isin(keep.conversation_id)].copy()
    out = msgs.merge(keep[["conversation_id", "question", "answer1", "answer2",
                           "persuader_answer", "persuader_type"]],
                     on="conversation_id", how="left")
    out = out.rename(columns={"id": "message_id"})
    return out.sort_values(["conversation_id", "message_id"])


def main():
    cfg = TagConfig(reasoning="high")
    print(f"tagger config: model={cfg.mdl} reasoning={cfg.reasoning}")
    df = build_input()
    convos = sorted(df.conversation_id.unique().tolist())
    print(f"{len(convos)} conversations with >=1 message")

    done = {}
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text().splitlines():
            rec = json.loads(line)
            done[rec["conversation_id"]] = rec["result"]
        print(f"resuming: {len(done)} in checkpoint")
    todo = [c for c in convos if c not in done]
    if "--smoke" in sys.argv:
        todo = todo[:4]
    print(f"{len(todo)} to tag", flush=True)

    with CHECKPOINT.open("a") as ckpt, ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(tag_one, df, c, cfg): c for c in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            c = futures[fut]
            done[c] = fut.result()
            ckpt.write(json.dumps({"conversation_id": c, "result": done[c]}) + "\n")
            ckpt.flush()
            if i % 50 == 0 or i == len(todo):
                errs = sum(1 for r in done.values() if r.get("status") == "error")
                print(f"{i}/{len(todo)} tagged ({errs} errors)", flush=True)

    if "--smoke" in sys.argv:
        for c in todo:
            print(c, json.dumps(done[c]))
        return

    types = df.drop_duplicates("conversation_id").set_index("conversation_id").persuader_type
    rows = [{"conversation_id": c,
             "persuader_type": types.get(c),
             "status": done[c].get("status"),
             "compliance": done[c].get("compliance"),
             "final_position": done[c].get("final_position"),
             "disclosed_assignment": done[c].get("disclosed_assignment"),
             "evidence": done[c].get("evidence", "")}
            for c in convos if c in done]
    out = pd.DataFrame(rows)
    out.to_csv(OUT_DIR / "position_compliance.csv", index=False)
    print(f"wrote {OUT_DIR}/position_compliance.csv ({len(out)} rows, "
          f"{(out.status == 'error').sum()} errors)")
    print(pd.crosstab(out.persuader_type, out.compliance))


if __name__ == "__main__":
    main()
