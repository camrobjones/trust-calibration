#!/usr/bin/env python3
"""Inter-rater reliability of the strategy tags (paper appendix).

Reads  ../data/tags/human_ratings.csv + ../data/tags/final_ratings_raw*.csv
Writes stats/irr_categories.csv  (15 final categories)
       stats/irr_strategies.csv  (the 26 individual strategies)

kappa = Cohen's kappa between the two human raters.
alpha = Krippendorff's alpha across the two humans and the final tagger.
Standard library only. Run from analysis/.
"""
import csv
from collections import Counter

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
STRATEGIES = sorted({s for cols in AGG_MAP.values() for s in cols})


def load(path, rater=None):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {(r.get("rater", rater), r["conversation_id"]): r for r in rows}


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe)


def alpha(units):
    """Krippendorff's alpha, nominal, complete data: units = list of rating tuples."""
    m = len(units[0])
    counts = Counter(v for u in units for v in u)
    total = m * len(units)
    Do = sum(sum(1 for i in u for j in u if i != j) / (m - 1) for u in units) / total
    De = sum(counts[a] * counts[b] for a in counts for b in counts if a != b) / (total * (total - 1))
    return 1 - Do / De


human = load("../data/tags/human_ratings.csv")
tagger = load("../data/tags/final_ratings_raw.csv", "tagger")
tagger.update(load("../data/tags/final_ratings_raw_addendum.csv", "tagger"))
ids = sorted({c for (r, c) in human if r == "rater1"} & {c for (r, c) in human if r == "rater2"}
             & {c for (r, c) in tagger}, key=int)
print(f"{len(ids)} conversations rated by both humans and the tagger")


def as_int(v):
    return int(float(v)) if v not in ("", None) else 0


def row(name, cols):
    r1 = [max(as_int(human["rater1", c][k]) for k in cols) for c in ids]
    r2 = [max(as_int(human["rater2", c][k]) for k in cols) for c in ids]
    t = [max(as_int(tagger["tagger", c][k]) for k in cols) for c in ids]
    return {"tag": name, "prevalence_humans": round((sum(r1) + sum(r2)) / (2 * len(ids)), 2),
            "agreement_humans": round(sum(a == b for a, b in zip(r1, r2)) / len(ids), 2),
            "kappa": round(kappa(r1, r2), 2), "alpha": round(alpha(list(zip(r1, r2, t))), 2)}


for path, table in (("stats/irr_categories.csv", [row(k, v) for k, v in AGG_MAP.items()]),
                    ("stats/irr_strategies.csv", [row(s, [s]) for s in STRATEGIES])):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(table)
    print("wrote", path)
