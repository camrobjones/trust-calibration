#!/usr/bin/env python3
"""Format stats/hypothesis_table.csv as per-experiment pre-registered-results tables.

Output: stats/hypothesis_tables.tex — six table environments matching the ones in
the manuscript: tab:e1-hypotheses .. tab:e4-hypotheses (E1/E2 report CC+PS rows; E3/E4 report
the pre-registered PS tests only) plus the appendix confidence-change tables tab:e3-cc
and tab:e4-cc. Rerun after any change to the stats CSV:  python3 make_hypothesis_table.py

Coefficients are displayed ORIENTED: positive = the direction stated in the Hypothesis
column. The stats CSV keeps raw reference-coded values; rows whose model term runs
opposite to the stated direction are listed in FLIP (hand-coded against the model
term names in e*_stats.csv — e.g. E1 H5a's term is intro_conditionMixed with Helpful
as reference, so "Helpful > Mixed" needs the sign flipped). In-text stats quote the
same oriented values; keep them in sync if any stat changes.

Support column: "yes" = significant (p < .05) in the predicted direction; "marg" =
marginal (.05 <= p < .10) in the predicted direction; "no" = not supported; "opp" =
significant in the direction OPPOSITE to the prediction (rendered x-dagger).
Verdicts are hand-coded below against the hypothesis statements in the paper /
preregs. Re-check them if any stat changes.
"""
import csv, re, collections

SRC = "stats/hypothesis_table.csv"
OUT = "stats/hypothesis_tables.tex"

# (experiment, collapsed-hypothesis) -> Hypothesis-column statement
STATEMENT = {
    ("E1", "H1"): r"Helpful $>$ chance",
    ("E1", "H2"): r"Mixed $>$ chance",
    ("E1", "H3"): r"Helpful $>$ chance (false claims)",
    ("E1", "H4"): r"Mixed $>$ chance (false claims)",
    ("E1", "H5ab"): r"Helpful $>$ Mixed",
    ("E1", "H5cd"): r"Mixed $>$ Unhelpful",
    ("E1", "H5ef"): r"Helpful $>$ Unhelpful",
    ("E1", "H6"): r"True $>$ false claims",
    ("E1", "H7ab"): r"Truth $\times$ Helpfulness (M $>$ H)",
    ("E1", "H7cd"): r"Truth $\times$ Helpfulness (U $>$ H)",
    ("E1", "H8"): r"Truth $\times$ Helpfulness (M $>$ U)",
    ("E2", "H1ab"): r"Helpful $>$ Mixed",
    ("E2", "H1cd"): r"Helpful $>$ Unhelpful",
    ("E2", "H2ab"): r"Helpfulness $\times$ Feedback (H vs.\ M)",
    ("E2", "H2cd"): r"Helpfulness $\times$ Feedback (H vs.\ U)",
    ("E3", "H1"): r"Conversation $>$ Hint",
    ("E3", "H2a"): r"Helpful $>$ Unhelpful (Conv + Feedback)",
    ("E3", "H2b"): r"Helpfulness $\times$ Mode (Feedback)",
    ("E3", "H3a"): r"Helpful $>$ Unhelpful (Conv + No Feedback)",
    ("E3", "H3b"): r"Helpfulness $\times$ Mode (No Feedback)",
    ("E3", "H4a"): r"Helpfulness $\times$ Feedback (Conv)",
    ("E3", "H4b"): r"Helpfulness $\times$ Feedback $\times$ Mode",
    ("E4", "H1a"): r"LLM $>$ Human",
    ("E4", "H2a"): r"Helpful $>$ Mixed (overall)",
    ("E4", "H2b"): r"Helpful $>$ Mixed (LLM)",
    ("E4", "H2c"): r"Helpful $>$ Mixed (Human)",
    ("E4", "H3a"): r"Helpfulness $\times$ Persuader type",
    ("E4", "H4a"): r"True $>$ false claims (overall)",
    ("E4", "H4b"): r"True $>$ false claims (LLM)",
    ("E4", "H4c"): r"True $>$ false claims (Human)",
    ("E4", "H4d"): r"Truth $\times$ Persuader type",
    ("E4", "H5a"): r"Final trial $>$ first trial (overall)",
    ("E4", "H5b"): r"Final trial $>$ first trial (LLM)",
    ("E4", "H5c"): r"Final trial $>$ first trial (Human)",
}

# Rows whose raw reference-coded coefficient runs opposite to the stated direction
# (verified against the term column in stats/e*_stats.csv).
FLIP = {
    ("E1", "H5ab"),  # term intro_conditionMixed, ref Helpful
    ("E1", "H5cd"),  # term intro_conditionUnhelpful, ref Mixed
    ("E1", "H5ef"),  # term intro_conditionUnhelpful, ref Helpful
    ("E1", "H8"),    # term persuader_correctTRUE:intro_conditionUnhelpful, ref Mixed
    ("E3", "H1"),    # term hint_conditionHint
    ("E3", "H2b"),   # term Helpful:Hint (negative = Hint reduces = stated)
    ("E3", "H3b"),   # term Helpful:Hint (negative = Hint reduces = stated)
    ("E3", "H4a"),   # term Helpful:No Feedback (negative = feedback increases = stated)
    ("E4", "H1a"),   # term interaction_typehuman_human
    ("E4", "H2a"),   # term intro_conditionMixed
    ("E4", "H2b"),   # term intro_conditionMixed
    ("E4", "H2c"),   # term intro_conditionMixed
    ("E4", "H5a"),   # term trial_typeintro
    ("E4", "H5b"),   # term trial_typeintro
    ("E4", "H5c"),   # term trial_typeintro
}

# (experiment, collapsed-hypothesis, measure) -> verdict
SUPPORT = {
    ("E1", "H1", "CC"): "yes",  ("E1", "H1", "PS"): "yes",
    ("E1", "H2", "CC"): "yes",  ("E1", "H2", "PS"): "yes",
    ("E1", "H3", "CC"): "yes",  ("E1", "H3", "PS"): "yes",
    ("E1", "H4", "CC"): "yes",  ("E1", "H4", "PS"): "yes",
    ("E1", "H5ab", "CC"): "yes",  ("E1", "H5ab", "PS"): "marg",
    ("E1", "H5cd", "CC"): "no",   ("E1", "H5cd", "PS"): "marg",
    ("E1", "H5ef", "CC"): "yes",  ("E1", "H5ef", "PS"): "yes",
    ("E1", "H6", "CC"): "no",   ("E1", "H6", "PS"): "no",
    ("E1", "H7ab", "CC"): "no", ("E1", "H7ab", "PS"): "no",
    ("E1", "H7cd", "CC"): "opp", ("E1", "H7cd", "PS"): "no",  # significant, opposite to prediction
    ("E1", "H8", "CC"): "yes",  ("E1", "H8", "PS"): "marg",
    ("E2", "H1ab", "CC"): "no", ("E2", "H1ab", "PS"): "no",
    ("E2", "H1cd", "CC"): "no", ("E2", "H1cd", "PS"): "no",
    ("E2", "H2ab", "CC"): "no", ("E2", "H2ab", "PS"): "no",
    ("E2", "H2cd", "CC"): "yes", ("E2", "H2cd", "PS"): "yes",
    ("E3", "H1", "CC"): "yes",  ("E3", "H1", "PS"): "yes",
    ("E3", "H2a", "CC"): "yes", ("E3", "H2a", "PS"): "yes",
    ("E3", "H2b", "CC"): "yes", ("E3", "H2b", "PS"): "no",
    ("E3", "H3a", "CC"): "no",  ("E3", "H3a", "PS"): "no",
    ("E3", "H3b", "CC"): "no",  ("E3", "H3b", "PS"): "no",
    ("E3", "H4a", "CC"): "yes", ("E3", "H4a", "PS"): "yes",
    ("E3", "H4b", "CC"): "marg", ("E3", "H4b", "PS"): "no",
    ("E4", "H1a", "CC"): "yes", ("E4", "H1a", "PS"): "yes",  # supports H1a over competing H1b
    ("E4", "H2a", "PS"): "yes",
    ("E4", "H2b", "CC"): "yes", ("E4", "H2b", "PS"): "yes",
    ("E4", "H2c", "CC"): "no",  ("E4", "H2c", "PS"): "no",
    ("E4", "H3a", "CC"): "yes", ("E4", "H3a", "PS"): "yes",
    ("E4", "H4a", "CC"): "yes", ("E4", "H4a", "PS"): "yes",
    ("E4", "H4b", "PS"): "marg",
    ("E4", "H4c", "PS"): "yes",
    ("E4", "H4d", "CC"): "marg", ("E4", "H4d", "PS"): "no",  # non-directional prediction
    ("E4", "H5a", "PS"): "no", ("E4", "H5b", "PS"): "no", ("E4", "H5c", "PS"): "no",
}
MARK = {"yes": r"\checkmark", "no": r"$\times$", "marg": "--", "opp": r"\smash{$\times^{\dagger}$}"}  # smash: dagger would stretch the row

ORIENT_NOTE = (r" oriented so that positive values correspond to the direction stated "
               r"in the Hypothesis column")
CAPTION = {
    "E1": (r"Pre-registered hypothesis tests in Experiment 1. Each hypothesis is tested "
           r"against persuader success (PS) and confidence change (CC). $b$ is the "
           r"coefficient for the tested contrast (log-odds for PS; percentage points of "
           r"confidence change for CC)," + ORIENT_NOTE + r". $n$ is the number of trials "
           r"in the model. In the interaction rows, H, M, and U denote the Helpful, Mixed, and "
           r"Unhelpful conditions, and $>$ gives the condition predicted to show the larger "
           r"truth advantage." "\n"
           r"Support: \checkmark\ ($p < .05$); -- ($p < .10$); $\times$ (not supported); "
           r"$\times^{\dagger}$ (significant in the opposite direction). "
           r"$^{\ddagger}$Estimated without the question random intercept, whose variance "
           r"was not identified in this subset (see text)."),
    "E2": (r"Pre-registered hypothesis tests in Experiment 2. $b$ is the coefficient for "
           r"the tested contrast (log-odds for PS; percentage points of confidence change "
           r"for CC)," + ORIENT_NOTE + r"; for the H2 interactions, positive values indicate a "
           r"larger helpfulness effect with feedback (Experiment 1) than without (Experiment 2); "
           r"H, M, and U denote the Helpful, Mixed, and Unhelpful conditions. "
           r"$n$ is the number of trials in the model."),
    "E3": (r"Pre-registered hypothesis tests in Experiment 3. $b$ is the log-odds "
           r"coefficient for the tested contrast," + ORIENT_NOTE + r". Conv = Conversation. For the interactions, "
           r"positive values indicate a smaller helpfulness effect for hints than conversations "
           r"(H2b, H3b), a larger helpfulness effect with feedback (H4a), and a larger feedback "
           r"effect for conversations than hints (H4b). $n$ is the number of trials in the model."),
    "E4": (r"Pre-registered hypothesis tests in Experiment 4. $b$ is the log-odds "
           r"coefficient for the tested contrast," + ORIENT_NOTE + r" (for H3a, positive values "
           r"indicate a larger helpfulness effect for LLMs; H4d made no "
           r"directional prediction; its coefficient is positive when the truth advantage "
           r"is larger for human persuaders). $n$ is the number of trials in the model."),
    "E3cc": (r"Confidence-change results for the hypothesis tests in Experiment 3 "
             r"(secondary, non-pre-registered measure; the pre-registered persuader-success "
             r"tests are reported in Table~\ref{tab:e3-hypotheses}). $b$ is the coefficient "
             r"for the tested contrast in percentage points of confidence change toward the "
             r"persuader's position," + ORIENT_NOTE + r". $n$ is the number of trials in the "
             r"model; interaction directions as in Table~\ref{tab:e3-hypotheses}. \checkmark\ = significant ($p<.05$) in the direction predicted for the "
             r"primary measure; -- = marginal ($.05 \le p < .10$); $\times$ = not significant."),
    "E4cc": (r"Confidence-change results for the hypothesis tests in Experiment 4 "
             r"(secondary, non-pre-registered measure; the pre-registered persuader-success "
             r"tests are reported in Table~\ref{tab:e4-hypotheses}). $b$ is the coefficient "
             r"for the tested contrast in percentage points of confidence change," +
             ORIENT_NOTE + r", as in Table~\ref{tab:e4-hypotheses}. Markers as in "
             r"Table~\ref{tab:e3-cc}."),
}

def rowkey(exp, hyp):
    if exp == "E1":
        m = re.match(r"H(\d)([a-f])", hyp)
        base, letter = m.group(1), m.group(2)
        if base in ("1", "2", "3", "4", "6", "8"):
            return f"H{base}"
        pair = {"a": "ab", "b": "ab", "c": "cd", "d": "cd", "e": "ef", "f": "ef"}[letter]
        return f"H{base}{pair}"
    if exp == "E2":
        m = re.match(r"H(\d)([a-d])", hyp)
        pair = {"a": "ab", "b": "ab", "c": "cd", "d": "cd"}[m.group(2)]
        return f"H{m.group(1)}{pair}"
    return hyp

def fmt_p(p_fmt):
    return p_fmt.replace("p < .001", "${<}.001$").replace("p = 0.", ".")

def oriented_b(exp, root, r):
    b = float(re.match(r"b = (-?[\d.]+),", r["stat_fmt"]).group(1))
    if (exp, root) in FLIP:
        b = -b
    dp = 1 if r["measure"] == "CC" else 2
    s = f"{abs(b):.{dp}f}"
    return f"$-${s}" if b < 0 else s  # true minus sign

rows = collections.OrderedDict()
order = []
NOQRE = {}  # (exp, hypothesis) -> row fit without the question random intercept
with open(SRC) as f:
    for r in csv.DictReader(f):
        if "noreassign" in r["hypothesis"]:
            continue  # robustness checks stay in-text
        if r["hypothesis"].endswith("_noqre"):
            NOQRE[(r["experiment"], r["hypothesis"][:-len("_noqre")])] = r
            continue
        key = (r["experiment"], rowkey(r["experiment"], r["hypothesis"]))
        if key not in rows:
            rows[key] = {}
            order.append(key)
        rows[key][r["measure"]] = r

# E1 H1b/H3b: the pre-registered model's question variance is not identified
# (see e1.Rmd "Sensitivity"), so the table shows the fit without it, marked.
SENS = set()
for (exp, hyp), r in NOQRE.items():
    root = rowkey(exp, hyp)
    rows[(exp, root)][r["measure"]] = r
    SENS.add((exp, root, r["measure"]))
SENS_MARK = r"\rlap{$^{\ddagger}$}"  # rlap keeps the b column aligned

by_exp = collections.OrderedDict()
for exp, root in order:
    by_exp.setdefault(exp, []).append(root)

def table_env(caption_key, label, colspec, tabcolsep, header, body):
    return ([rf"% ---- {label} ----", r"\begin{table}", r"\centering",
             rf"\caption{{{CAPTION[caption_key]}}}", rf"\label{{{label}}}",
             r"\scriptsize", rf"\setlength{{\tabcolsep}}{{{tabcolsep}}}",
             rf"\begin{{tabular}}{{{colspec}}}", r"\toprule", header, r"\midrule"]
            + body + [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])

# Tables split the pre-registered label into a hypothesis-number column and a
# sub-letter column (H5 | a, b, c, ...), with a thin rule between hypothesis
# numbers. E1/E2 letters follow the prereg: CC = first letter, PS = second.
THIN_RULE = r"\cmidrule[0.2pt]{{1-{}}}"


def split_root(root):
    m = re.match(r"^(H\d)([a-f]*)$", root)
    return m.group(1), m.group(2)


def two_measure_body(exp, roots):
    """E1/E2: a CC row and a PS row per contrast."""
    body, prev = [], None
    for root in roots:
        num, letters = split_root(root)
        letters = letters or "ab"
        if prev is not None and num != prev:
            body.append(THIN_RULE.format(8))
        entry = rows[(exp, root)]
        for i, meas in enumerate(("CC", "PS")):
            if meas not in entry:
                continue
            r = entry[meas]
            num_cell = num if (num != prev and i == 0) else ""
            stmt = STATEMENT[(exp, root)] if i == 0 else ""
            mark = SENS_MARK if (exp, root, meas) in SENS else ""
            body.append(rf"{num_cell} & {letters[i]} & {stmt} & {meas} & {oriented_b(exp, root, r)}{mark} & "
                        rf"{fmt_p(r['p_fmt'])} & {r['n']} & {MARK[SUPPORT[(exp, root, meas)]]} \\")
        prev = num
    return body


def one_measure_body(exp, roots, meas):
    """E3/E4: one row per hypothesis for the given measure."""
    body, prev = [], None
    for root in roots:
        entry = rows[(exp, root)]
        if meas not in entry:
            continue
        num, letter = split_root(root)
        if prev is not None and num != prev:
            body.append(THIN_RULE.format(7))
        r = entry[meas]
        body.append(rf"{num if num != prev else ''} & {letter} & {STATEMENT[(exp, root)]} & "
                    rf"{oriented_b(exp, root, r)} & {fmt_p(r['p_fmt'])} & {r['n']} & "
                    rf"{MARK[SUPPORT[(exp, root, meas)]]} \\")
        prev = num
    return body


out = []
for exp, roots in by_exp.items():
    if exp in ("E1", "E2"):
        out += table_env(exp, f"tab:{exp.lower()}-hypotheses", "llllrrrc",
                         "5pt" if exp == "E1" else "4pt",  # E2's long statements overflow at 5pt
                         r"H. & & Hypothesis & Measure & $b$ & $p$ & $n$ & Support \\",
                         two_measure_body(exp, roots))
    else:
        out += table_env(exp, f"tab:{exp.lower()}-hypotheses", "lllrrrc", "5pt",
                         r"H. & & Hypothesis & $b$ & $p$ & $n$ & Support \\",
                         one_measure_body(exp, roots, "PS"))
        out += table_env(exp + "cc", f"tab:{exp.lower()}-cc", "lllrrrc", "5pt",
                         r"H. & & Hypothesis & $b$ & $p$ & $n$ & Sig. \\",
                         one_measure_body(exp, roots, "CC"))

with open(OUT, "w") as f:
    f.write("\n".join(out) + "\n")
print(f"wrote {OUT}")
emitted = {(e, r, m) for (e, r) in order for m in rows[(e, r)]}
unused = set(SUPPORT) - emitted
if unused:
    print("WARNING unused SUPPORT keys:", sorted(unused))
missing_stmt = {(e, r) for (e, r) in order if (e, r) not in STATEMENT}
if missing_stmt:
    print("WARNING rows missing STATEMENT:", sorted(missing_stmt))
