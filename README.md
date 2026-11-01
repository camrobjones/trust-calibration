# Do people trust AI assistants even when they are consistently wrong?

Data, analysis code, and materials.

## Reproduce the results

You need R 4.5 with the packages in [`R_environment.txt`](R_environment.txt), pandoc, and Python 3
(standard library only). From this folder, run:

```bash
Rscript run_all.R
```

The script should take around 5 minutes to run. It will re-render all of the statistics, analysis, and figures used in the paper.

## Structure

| Folder | Contents |
|---|---|
| `data/` | De-identified data and LLM tags. [`data/README.md`](data/README.md) is the data dictionary and describes the de-identification |
| `analysis/` | Analysis scripts, rendered reports, and generated statistics |
| `figures/` | Data figures |
| `tagging/` | Code, codebook, and reliability report for the LLM strategy tags |
| `experiment_code/` | The experiment software, as deployed |

Materials are in `data/`: questions in `conversation_Question.csv`, advisor system prompts in
`conversation_AIPersuader.csv`, and the Susceptibility to Persuasion items in
`conversation_PersuadabilityQuestion.csv`. The exit survey is reproduced in the paper's appendix.
Preregistrations are linked from the manuscript.


## Locating specific results

| Result type | Script | Output |
|---|---|---|
| Experiment 1 | `analysis/e1.Rmd` | `e1.html`, `stats/e1_*.csv` |
| Experiment 2 | `analysis/e2.Rmd` | `e2.html`, `stats/e2_*.csv` |
| Experiment 3 | `analysis/e3.Rmd` | `e3.html`, `stats/e3_*.csv` |
| Experiment 4 | `analysis/e4.Rmd` | `e4.html`, `stats/e4_*.csv` |
| Persuasion Strategies; Concession and Non-Compliance; Truth Advantage | `analysis/qualitative_tags.Rmd` | `qualitative_tags.html`, `stats/qual_*.csv` |
| Individual Differences; pooled analyses | `analysis/cross_experiments.Rmd` | `cross_experiments.html`, `stats/stp_coefs.csv`, `stats/id_*.csv`, `stats/expertise_by_domain.csv` |
| Preregistered-hypothesis tables | `analysis/make_hypothesis_table.py` | `stats/hypothesis_table.csv`, `stats/hypothesis_tables.tex` |
| Question frequency table (appendix) | `analysis/make_question_freq_table.py` | `stats/appendix_question_freq.tex` |
| Reliability of the strategy tags (appendix) | `analysis/irr.py` | `stats/irr_categories.csv`, `stats/irr_strategies.csv` |
| Main figures for each experiment, track-record baseline, strategy figures | `analysis/paper_figs.Rmd` | `figures/e*_main.pdf`, `figures/e4_baseline.pdf`, `figures/qual_*.pdf` |
| Cross-experiment figures | `analysis/fig_explorations.R` | `figures/xp_truth.pdf`, `figures/xp_questions.pdf`, `figures/xp_stp.pdf` |


## License

Data are CC BY 4.0 and code is MIT. See [`LICENSE`](LICENSE).
