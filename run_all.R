#!/usr/bin/env Rscript
# Reproduce all analyses.
# Run from the repository root:  Rscript run_all.R
# See README.md.

if (!file.exists("analysis/e1.Rmd")) stop("Run this from the repository root.")

required <- c("tidyverse", "rmarkdown", "knitr", "kableExtra", "lme4", "lmerTest", "MASS",
              "broom", "broom.mixed", "cowplot", "patchwork", "ggtext", "ggrepel", "scales")
missing <- setdiff(required, rownames(installed.packages()))
if (length(missing)) stop("Missing packages: ", paste(missing, collapse = ", "),
                         ". See R_environment.txt for the versions we used.")

root <- getwd()
dir.create("figures/drafts/explore", recursive = TRUE, showWarnings = FALSE)
render <- function(f) {
  message("Rendering ", f)
  setwd(file.path(root, "analysis"))
  rmarkdown::render(f, envir = new.env(), quiet = TRUE)
  setwd(root)
}

# Experiment analyses must be run before cross-experiment analyses
for (f in c("e1.Rmd", "e2.Rmd", "e3.Rmd", "e4.Rmd", "cross_experiments.Rmd",
            "qualitative_tags.Rmd", "paper_figs.Rmd")) render(f)

setwd(file.path(root, "analysis"))
message("Rendering standalone figures")
# UTF-8 locale keeps the dagger labels intact under Rscript
stopifnot(system2("Rscript", "fig_explorations.R", env = "LC_ALL=en_US.UTF-8") == 0)
message("Formatting tables")
stopifnot(system2("python3", "make_hypothesis_table.py") == 0)
stopifnot(system2("python3", "make_question_freq_table.py") == 0)
stopifnot(system2("python3", "irr.py") == 0)
setwd(root)

if (file.exists("analysis/stats/CHECKSUMS.md5")) source("check_outputs.R")
