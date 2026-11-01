#!/usr/bin/env Rscript
# paper_figs_apa.R -- re-render the paper's R figures at true print size for the
# two APA layouts, without changing what they show:
#   Rscript paper_figs_apa.R ms     # submission manuscript, 6.5in text block
#   Rscript paper_figs_apa.R 2col   # two-column preprint,   6.96in text block
#   (add "explore" as a second argument to re-render only the xp_* figures)
#
# Figure code stays in paper_figs.Rmd and fig_explorations.R. This driver runs
# those files with ggsave()/save_pdf() redirected to figures/apa_<format>/ at
# the sizes below (the wired figures/*.pdf are never touched), so a change to a
# panel only has to be made once. Run from conversation/analysis/.

suppressMessages({
  library(tidyverse); library(cowplot); library(patchwork); library(ggtext)
})

Sys.setlocale("LC_ALL", "en_US.UTF-8")  # keeps the dagger labels intact under Rscript
FORMAT <- commandArgs(TRUE)[1]
stopifnot(FORMAT %in% c("ms", "2col"))

ROOT_FIG <- "../figures"
OUT_DIR  <- file.path(ROOT_FIG, paste0("apa_", FORMAT))
dir.create(OUT_DIR, showWarnings = FALSE)

# width x height in inches. Width = \textwidth, so the PDF prints 1:1 and text
# keeps its true point size. Heights leave room for title + note on one page.
SIZES <- list(
  ms = list(
    e1_main = c(6.5, 6.45), e2_main = c(6.5, 6.45), e3_main = c(6.5, 6.75),
    e4_main = c(6.5, 6.45), e4_baseline = c(6.5, 2.9),
    qual_main = c(6.5, 5.9), qual_probes = c(6.5, 5.9), qual_items = c(6.5, 6.9),
    xp_truth = c(6.5, 6.3), xp_questions = c(6.5, 6.4), xp_stp = c(6.5, 6.1)
  ),
  `2col` = list(
    e1_main = c(6.96, 5.9), e2_main = c(6.96, 5.9), e3_main = c(6.96, 6.9),
    e4_main = c(6.96, 5.9), e4_baseline = c(6.96, 2.8),
    qual_main = c(6.96, 5.6), qual_probes = c(6.96, 5.6), qual_items = c(6.96, 6.4),
    xp_truth = c(6.96, 5.6), xp_questions = c(6.96, 5.7), xp_stp = c(6.96, 6.9)
  )
)[[FORMAT]]

quartz_pdf <- function(filename, width, height, ...)
  if (!capabilities("aqua")) grDevices::cairo_pdf(filename, width = width, height = height) else
  grDevices::quartz(file = filename, type = "pdf", width = width, height = height, ...)

save_print <- function(name, plot) {
  sz <- SIZES[[name]]
  if (is.null(sz)) return(invisible())
  ggplot2::ggsave(file.path(OUT_DIR, paste0(name, ".pdf")), plot,
                  width = sz[1], height = sz[2], device = quartz_pdf, bg = "white")
  message("saved ", name, " ", sz[1], " x ", sz[2])
}

ONLY_EXPLORE <- identical(commandArgs(TRUE)[2], "explore")  # skip to the xp_* figures

# --- paper_figs.Rmd ----------------------------------------------------------
# Masks ggplot2::ggsave for the chunks below; DRAFT PNGs are skipped.
ggsave <- function(filename, plot = last_plot(), ...) {
  if (grepl("DRAFT", filename)) return(invisible())
  save_print(tools::file_path_sans_ext(basename(filename)), plot)
}

lines  <- readLines("paper_figs.Rmd", encoding = "UTF-8")
starts <- grep("^```\\{r ", lines)
chunk_code <- function(s) {
  e <- s + which(lines[(s + 1):length(lines)] == "```")[1]
  lines[(s + 1):(e - 1)]
}
# Densest figures (E3's 2x2 facets, the qualitative forests) print at 9pt so their
# strips and row labels fit; the rest stay at 10pt.
BASE_AT <- c("e3-data" = 9, "e4-data" = 10, "qual-data" = 9)
design_code <- NULL
for (s in if (ONLY_EXPLORE) integer(0) else starts) {
  label <- sub("^```\\{r ([A-Za-z0-9-]+).*", "\\1", lines[s])
  if (grepl("sanity|backups|^setup$", label)) next
  code <- chunk_code(s)
  if (label == "design") design_code <- code
  if (label %in% names(BASE_AT)) {
    patched <- sub("^BASE_SIZE +<- +10", paste("BASE_SIZE <-", BASE_AT[[label]]), design_code)
    eval(parse(text = patched), envir = globalenv())
  }
  message("chunk ", label)
  eval(parse(text = code), envir = globalenv())
}

# --- fig_explorations.R (xp_truth, xp_stp, xp_questions) ---------------------
src <- readLines("fig_explorations.R", encoding = "UTF-8")
at  <- grep("^# --- data ---", src)[1]
src <- append(src, c(
  "save_png <- function(...) invisible()",
  "save_pdf <- function(name, plot, ...) save_print(name, plot)"
), after = at - 1)
src <- sub("^BASE_SIZE +<- +10", "BASE_SIZE <- 9", src)
# xp_stp is shorter here than the 8.6in original, so give the per-experiment forest more of it
src <- sub("plot_layout(heights = c(1, 0.5, 1.1))", "plot_layout(heights = c(0.85, 0.62, 1.1))", src, fixed = TRUE)
explore <- new.env(parent = globalenv())
eval(parse(text = src), envir = explore)
