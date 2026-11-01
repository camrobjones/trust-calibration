#!/usr/bin/env Rscript
# Compares analysis/stats/ with the checksums of the outputs behind the paper.
# Run from the repository root:  Rscript check_outputs.R
# Small numeric differences can arise under other R or lme4 versions.

expected <- read.table("analysis/stats/CHECKSUMS.md5", col.names = c("md5", "file"),
                       stringsAsFactors = FALSE)
actual <- tools::md5sum(file.path("analysis/stats", expected$file))
same <- !is.na(actual) & unname(actual) == expected$md5

cat(sprintf("%d of %d output files match the published outputs.\n", sum(same), length(same)))
if (!all(same)) {
  cat("Differ:\n", paste0("  ", expected$file[!same], collapse = "\n"), "\n", sep = "")
  quit(status = 1)
}
