
suppressMessages({
  library(tidyverse)
  library(cowplot)
  library(patchwork)
  library(ggtext)   # element_markdown: small daggers inside axis tick labels
})

# --- design (mirrors paper_figs.Rmd) -----------------------------------------
PAL_CONDITION <- c("Helpful" = "#117733", "Mixed" = "#CC9933", "Unhelpful" = "#CC3311")
PAL_TRUTH     <- c("Truth" = "#4477AA", "Falsehood" = "#EE6677")
PAL_PERSUADER <- c("LLM" = "#009988", "Human" = "#AA4499")  # validated; deutan dE 7.5
                                                            # -> always paired with facet/direct labels
PAL_TOPIC     <- c("logic" = "#332288", "physics" = "#88CCEE",
                   "probability" = "#DDCC77", "facts" = "#999933")
# Okabe-Ito alternative (validated; identity also carried by adjacent labels)
PAL_TOPIC2    <- c("logic" = "#CC79A7", "physics" = "#56B4E9",
                   "probability" = "#E69F00", "facts" = "#009E73")
# questions dropped from the E4 set (marked with a dagger in by-item figs)
E4_REMOVED    <- c("bathtub", "bullet", "coins", "ireland", "nuts", "sourdough")
BASE_SIZE  <- 10
LAB_PS     <- "Persuader success"
LAB_CC     <- "Confidence change"
LAB_CONF   <- "Initial confidence in own answer"
LAB_TRUTH  <- "Persuader argues"
LINE_WIDTH   <- 0.7
EB_LINEWIDTH <- 0.5
theme_paper <- theme_minimal_hgrid(BASE_SIZE) +
  theme(
    plot.title      = element_text(size = BASE_SIZE, face = "plain", hjust = 0.5),
    plot.subtitle   = element_text(size = BASE_SIZE - 3.5, hjust = 0.5,
                                   color = "grey45", margin = margin(b = 2)),
    axis.title.x    = element_text(margin = margin(t = 1)),
    legend.position = "bottom",
    legend.justification = "center",
    legend.title    = element_text(face = "plain"),
    plot.tag        = element_text(face = "bold")
  )
SEED   <- 42
ci_fun <- mean_cl_boot
# default optimizer fails to converge on the E3 per-experiment glmer (garbage
# SE 0.001); bobyqa converges cleanly on all fits
GLMER_CTRL <- lme4::glmerControl(optimizer = "bobyqa",
                                 optCtrl = list(maxfun = 2e5))
OUT     <- "../figures/drafts/explore"
FIG_DIR <- "../figures"
dir.create(OUT, recursive = TRUE, showWarnings = FALSE)
save_png <- function(name, plot, w = 6.5, h = 3.2)
  ggsave(file.path(OUT, paste0(name, ".png")), plot, width = w, height = h,
         dpi = 220, bg = "white")
# macOS quartz pdf: cairo DLL is unavailable in this R build, and the base pdf
# device drops the dagger glyph (renders as "."); quartz handles unicode
quartz_pdf <- function(filename, width, height, ...)
  if (!capabilities("aqua")) grDevices::cairo_pdf(filename, width = width, height = height) else
  grDevices::quartz(file = filename, type = "pdf",
                    width = width, height = height, ...)
save_pdf <- function(name, plot, w = 6.5, h = 3.2)
  ggsave(file.path(FIG_DIR, paste0(name, ".pdf")), plot, width = w, height = h,
         device = quartz_pdf, bg = "white")

# --- data --------------------------------------------------------------------
questions <- read.csv("../data/conversation_Question.csv") %>%
  select(question_id = id, name, subcategory)

trials <- map_dfr(sprintf("stats/e%d_trials.csv", 1:4), read.csv) %>%
  left_join(questions, by = "question_id") %>%
  mutate(
    persuader_success = as.numeric(persuader_success),  # logical is DISCRETE to ggplot
    truth = factor(ifelse(persuader_correct, "Truth", "Falsehood"), names(PAL_TRUTH)),
    persuader_type = factor(ifelse(interaction_type == "human_human", "Human", "LLM"),
                            names(PAL_PERSUADER))
  )
disagree <- filter(trials, participant_persuader_disagree)

# StP-II: same construction as the old combined_analysis.Rmd (rt > 4000 ms
# mean-RT retention; score = mean of scoring * response per subscale)
stp_resp <- read.csv("../data/conversation_PersuadabilityResponse.csv")
stp_q    <- read.csv("../data/conversation_PersuadabilityQuestion.csv")
stp_keep <- stp_resp %>% group_by(participant_id) %>%
  summarize(rt = mean(reaction_time)) %>% filter(rt > 4000) %>% pull(participant_id)
stp_scores <- stp_resp %>%
  filter(participant_id %in% stp_keep) %>%
  left_join(stp_q %>% select(item_id, category), by = c("question_id" = "item_id")) %>%
  group_by(participant_id, category) %>%
  summarize(score = mean(scoring * response), .groups = "drop")
stp_total <- stp_scores %>% group_by(participant_id) %>%
  summarize(score = mean(score)) %>% mutate(category = "total StP")
stp_all <- bind_rows(stp_scores, stp_total)

stp_trials <- trials %>%
  filter(experiment %in% c("E1", "E2", "E3")) %>%
  inner_join(stp_total %>% select(participant_id, stp = score), by = "participant_id")
stp_disagree <- filter(stp_trials, participant_persuader_disagree)

# --- helpers -----------------------------------------------------------------
# binned observed rates + logistic fit; grouped version uses wider bins.
# facet_var must be passed so the binned points are computed per facet
# (the smooths are per-panel automatically; the summary layer is not).
conf_plot <- function(d, color_var = NULL, binwidth = 10, facet_var = NULL) {
  b <- d %>%
    mutate(bin = floor(pmin(confidence_pre, 99) / binwidth) * binwidth + binwidth / 2)
  grp <- c(color_var, facet_var, "bin")
  if (is.null(color_var)) {
    bins <- b %>% group_by(across(all_of(grp))) %>%
      summarize(ps = mean(persuader_success), n = n(), .groups = "drop")
    p <- ggplot(d, aes(confidence_pre, persuader_success)) +
      geom_smooth(method = "glm", method.args = list(family = "binomial"),
                  color = "grey25", fill = "grey70", linewidth = LINE_WIDTH) +
      geom_point(data = bins, aes(bin, ps, size = n),
                 shape = 16, color = "grey25", alpha = 0.6)
  } else {
    bins <- b %>% group_by(across(all_of(grp))) %>%
      summarize(ps = mean(persuader_success), n = n(), .groups = "drop")
    p <- ggplot(d, aes(confidence_pre, persuader_success,
                       color = .data[[color_var]], fill = .data[[color_var]])) +
      geom_smooth(aes(linetype = .data[[color_var]]),
                  method = "glm", method.args = list(family = "binomial"),
                  linewidth = LINE_WIDTH, alpha = 0.25) +
      geom_point(data = bins, aes(bin, ps, size = n), shape = 16, alpha = 0.6)
  }
  p +
    scale_size_area(max_size = 3.5, guide = "none") +
    scale_y_continuous(labels = scales::percent) +
    scale_x_continuous(breaks = c(0, 50, 100)) +
    coord_cartesian(ylim = c(0, 1)) +
    labs(x = LAB_CONF, y = LAB_PS) +
    theme_paper
}

# binned points + linear/logistic fit for a generic x (StP scores)
score_plot <- function(d, xvar, yvar = "persuader_success", bins = 10,
                       family = "binomial") {
  p <- ggplot(d, aes(.data[[xvar]], .data[[yvar]])) +
    stat_summary_bin(geom = "point", fun = "mean", bins = bins,
                     shape = 16, color = "grey25", alpha = 0.7) +
    stat_summary_bin(geom = "errorbar", fun.data = ci_fun, bins = bins,
                     width = 0, linewidth = EB_LINEWIDTH, color = "grey25") +
    theme_paper
  if (family == "binomial") {
    p <- p + geom_smooth(method = "glm", method.args = list(family = "binomial"),
                         color = "#4477AA", fill = "grey70", linewidth = LINE_WIDTH) +
      scale_y_continuous(labels = scales::percent) +
      coord_cartesian(ylim = c(0, 1))
  } else {
    p <- p + geom_smooth(method = "lm", formula = y ~ x,
                         color = "#4477AA", fill = "grey70", linewidth = LINE_WIDTH)
  }
  p
}

set.seed(SEED)
# linetype doubles the colour signal on grouped fits (CVD-safe habit; the
# persuader pair is in the deutan floor band so it is REQUIRED there)
lt_scale <- function(name) scale_linetype_manual(name = name,
                                                 values = c("solid", "42"))

# =============================================================================
# (i) initial confidence vs persuader success
# =============================================================================
message("family i: confidence")

i1 <- conf_plot(disagree) +
  labs(title = "Pooled E1-E4", subtitle = "Disagreement Trials Only")
save_png("i1_conf_overall", i1, w = 3.4, h = 3.0)

i2 <- conf_plot(disagree, facet_var = "experiment") +
  facet_grid(. ~ experiment) +
  labs(title = NULL, subtitle = "Disagreement Trials Only")
save_png("i2_conf_byexp", i2, w = 6.5, h = 2.6)

i3 <- conf_plot(disagree, "truth", binwidth = 20) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH) +
  labs(title = "Truth effect by confidence (pooled E1-E4)",
       subtitle = "Disagreement Trials Only")
save_png("i3_conf_truth_pooled", i3, w = 3.6, h = 3.4)

i4 <- conf_plot(disagree, "truth", binwidth = 25, facet_var = "experiment") +
  facet_grid(. ~ experiment) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH) +
  labs(subtitle = "Disagreement Trials Only")
save_png("i4_conf_truth_byexp", i4, w = 6.5, h = 2.9)

i5a <- conf_plot(disagree, "persuader_type", binwidth = 20) +
  scale_color_manual(name = "Persuader", values = PAL_PERSUADER) +
  scale_fill_manual(name = "Persuader", values = PAL_PERSUADER) +
  lt_scale("Persuader") +
  labs(title = "By persuader type (pooled E1-E4)",
       subtitle = "Disagreement Trials Only")
save_png("i5a_conf_persuader_pooled", i5a, w = 3.6, h = 3.4)

i5b <- conf_plot(filter(disagree, experiment == "E4"), "persuader_type",
                 binwidth = 25) +
  scale_color_manual(name = "Persuader", values = PAL_PERSUADER) +
  scale_fill_manual(name = "Persuader", values = PAL_PERSUADER) +
  lt_scale("Persuader") +
  labs(title = "By persuader type (E4 only)",
       subtitle = "Disagreement Trials Only")
save_png("i5b_conf_persuader_e4", i5b, w = 3.6, h = 3.4)

i6 <- conf_plot(filter(disagree, experiment == "E4"), "truth", binwidth = 25,
                facet_var = "persuader_type") +
  facet_grid(. ~ persuader_type) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH) +
  labs(title = "E4: truth x persuader type", subtitle = "Disagreement Trials Only")
save_png("i6_conf_truth_x_persuader_e4", i6, w = 5.0, h = 3.4)

# agree-vs-disagree contrast (the old combined_analysis 2x2)
i7 <- conf_plot(
  trials %>% mutate(agree = ifelse(participant_persuader_disagree,
                                   "Participant disagrees", "Participant agrees")),
  "truth", binwidth = 20, facet_var = "agree") +
  facet_grid(. ~ agree) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH) +
  labs(title = "All trials, by prior agreement (pooled E1-E4)")
save_png("i7_conf_truth_x_agreement", i7, w = 5.6, h = 3.4)

# =============================================================================
# (i-GD) truth advantage by channel: the General Discussion multipanel.
# One visual grammar for the GD's three claims: the advantage needs high prior
# confidence (curves diverge only at the top), needs discourse (no divergence
# for bare hints), and is larger for human persuaders.
# =============================================================================
message("family i-GD: truth-by-channel")

gd <- disagree %>%
  mutate(
    channel = factor(case_when(
      experiment == "E3" & !is.na(hint_condition) & hint_condition == "Hint" ~
        "Hint only (E3)",
      persuader_type == "Human" ~ "Human conversation (E4)",
      TRUE ~ "LLM conversation (E1-E4)"
    ), c("LLM conversation (E1-E4)", "Hint only (E3)", "Human conversation (E4)"))
  )

gd_truth <- conf_plot(gd, "truth", binwidth = 25, facet_var = "channel") +
  facet_grid(. ~ channel) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH) +
  labs(subtitle = "Disagreement Trials Only") +
  theme(strip.text = element_text(size = BASE_SIZE - 1))
save_png("GD_truth_by_channel", gd_truth, w = 6.5, h = 3.2)

# composition check: intro trials only (E3/E4 finals argue falsehoods
# disproportionately, so the pooled falsehood curve leans on them)
gd_truth_intro <- conf_plot(filter(gd, trial_type == "intro"), "truth",
                            binwidth = 25, facet_var = "channel") +
  facet_grid(. ~ channel) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH) +
  labs(subtitle = "Intro Disagreement Trials Only") +
  theme(strip.text = element_text(size = BASE_SIZE - 1))
save_png("GD_truth_by_channel_introsonly", gd_truth_intro, w = 6.5, h = 3.2)

# within-E3 version (mode randomised within one design; truth == helpfulness
# caveat applies to both cells equally)
gd_e3 <- conf_plot(filter(disagree, experiment == "E3"), "truth",
                   binwidth = 25, facet_var = "hint_condition") +
  facet_grid(. ~ hint_condition) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH) +
  labs(title = "E3 only: mode randomised within-study",
       subtitle = "Disagreement Trials Only") +
  theme(strip.text = element_text(size = BASE_SIZE - 1))
save_png("GD_truth_e3_mode", gd_e3, w = 5.0, h = 3.4)

truth_scales <- function(p) p +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_fill_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  lt_scale(LAB_TRUTH)
strip_sm <- theme(strip.text = element_text(size = BASE_SIZE - 1.5),
                  panel.spacing = unit(4, "pt"))

# two candidate clean sets: strict (randomised/first only) vs +NF (adds the
# H3a-null-licensed no-feedback trials) -- built side by side for comparison
clean_strict <- disagree %>%
  filter(
    (experiment != "E3" & trial_type == "final") |
      (trial_type == "intro" & trial_index == 0)
  )
clean_nf <- disagree %>%
  filter(
    (experiment != "E3" & (trial_type == "final" | intro_condition == "Mixed")) |
      (trial_type == "intro" & trial_index == 0) |
      (!is.na(feedback_condition) & feedback_condition == "No Feedback")
  )

make_gd <- function(clean, sub_llm, sub_e3) {
  clean_llm <- clean %>%
    filter(persuader_type == "LLM",
           is.na(hint_condition) | hint_condition != "Hint")
  clean_e3 <- filter(clean, experiment == "E3")
  clean_e4 <- filter(clean, experiment == "E4")
  message("cell ns (", sub_e3, "):")
  print(clean_llm %>% count(truth))
  print(clean_e3 %>% count(hint_condition, truth))
  print(clean_e4 %>% count(persuader_type, truth))

  pa <- conf_plot(disagree) +
    labs(title = "Overall", subtitle = "All disagreement trials (E1-E4)",
         x = NULL)
  pb <- truth_scales(conf_plot(clean_llm, "truth", 25)) +
    labs(title = "LLM conversations", subtitle = sub_llm,
         x = NULL, y = NULL)
  pc <- truth_scales(conf_plot(clean_e3, "truth", 25, "hint_condition") +
                       facet_grid(. ~ hint_condition)) +
    labs(title = "Conversation vs. hint", subtitle = sub_e3,
         x = LAB_CONF) + strip_sm
  pd <- truth_scales(conf_plot(clean_e4, "truth", 25, "persuader_type") +
                       facet_grid(. ~ persuader_type)) +
    labs(title = "LLM vs. human persuaders",
         subtitle = "First or final trial (E4)",
         x = LAB_CONF, y = NULL) + strip_sm

  ((pa | pb) / (pc | pd)) +
    plot_layout(guides = "collect") +
    plot_annotation(tag_levels = "a") &
    theme(legend.position = "bottom", legend.justification = "center")
}

gd_nf <- make_gd(clean_nf,
                 "Truth randomised, first, or no-feedback trials (E1-E4)",
                 "First or no-feedback trials (E3)")
save_png("GD_truth_4panel_withNF", gd_nf, w = 6.5, h = 6.4)

gd_strict <- make_gd(clean_strict,
                     "First or final trial (E1-E4)",
                     "First trials (E3)")
save_png("GD_truth_4panel_strict", gd_strict, w = 6.5, h = 6.4)

save_pdf("xp_truth", gd_strict, w = 6.5, h = 6.4)

# =============================================================================
# (ii) StP-II
# =============================================================================
message("family ii: StP")

ii1a <- score_plot(stp_trials, "stp") +
  labs(x = "StP-II (total)", y = LAB_PS, title = "All trials (E1-E3)")
ii1b <- score_plot(stp_disagree, "stp") +
  labs(x = "StP-II (total)", y = LAB_PS, title = "Disagreement trials (E1-E3)")
save_png("ii1_stp_ps", ii1a | ii1b, w = 6.0, h = 3.0)

ii2a <- score_plot(stp_trials, "stp", "confidence_change", family = "gaussian") +
  labs(x = "StP-II (total)", y = LAB_CC, title = "All trials (E1-E3)")
ii2b <- score_plot(stp_disagree, "stp", "confidence_change", family = "gaussian") +
  labs(x = "StP-II (total)", y = LAB_CC, title = "Disagreement trials (E1-E3)")
save_png("ii2_stp_cc", ii2a | ii2b, w = 6.0, h = 3.0)

ii3 <- score_plot(stp_disagree, "stp") + facet_grid(. ~ experiment) +
  labs(x = "StP-II (total)", y = LAB_PS, subtitle = "Disagreement Trials Only")
save_png("ii3_stp_ps_byexp", ii3, w = 6.0, h = 2.8)

ii4 <- score_plot(filter(stp_disagree, experiment == "E3"), "stp") +
  facet_grid(. ~ hint_condition) +
  labs(x = "StP-II (total)", y = LAB_PS,
       title = "E3 by mode", subtitle = "Disagreement Trials Only")
save_png("ii4_stp_ps_e3_mode", ii4, w = 5.0, h = 3.0)

# subscale grid: PS (disagree) vs each subscale, z-scored x for comparability
stp_long <- stp_all %>%
  group_by(category) %>% mutate(z = as.numeric(scale(score))) %>% ungroup() %>%
  inner_join(disagree %>% filter(experiment != "E4") %>%
               select(participant_id, question_id, persuader_success,
                      confidence_change),
             by = "participant_id", relationship = "many-to-many")

ii5 <- ggplot(stp_long, aes(z, persuader_success)) +
  stat_summary_bin(geom = "point", fun = "mean", bins = 8,
                   shape = 16, color = "grey25", alpha = 0.7) +
  geom_smooth(method = "glm", method.args = list(family = "binomial"),
              color = "#4477AA", fill = "grey70", linewidth = LINE_WIDTH) +
  scale_y_continuous(labels = scales::percent) +
  coord_cartesian(ylim = c(0, 1), xlim = c(-2.5, 2.5)) +
  facet_wrap(~category, nrow = 3) +
  labs(x = "Subscale score (z)", y = LAB_PS, subtitle = "Disagreement Trials Only") +
  theme_paper +
  theme(strip.text = element_text(size = BASE_SIZE - 2))
save_png("ii5_stp_subscale_grid", ii5, w = 6.5, h = 5.2)

# forest of per-subscale coefficients (z-scored), PS logistic + CC linear;
# mixed models (ppt + question intercepts) so the trial-level SEs are honest
forest <- stp_long %>%
  pivot_longer(c(persuader_success, confidence_change),
               names_to = "measure", values_to = "y") %>%
  mutate(measure = factor(measure, c("persuader_success", "confidence_change"),
                          c("Persuader success (log-odds per SD)",
                            "Confidence change (points per SD)"))) %>%
  group_by(measure, category) %>%
  group_modify(function(d, g) {
    m <- if (grepl("success", g$measure))
      lme4::glmer(y ~ z + (1 | participant_id) + (1 | question_id),
                  family = binomial, data = d, control = GLMER_CTRL)
    else
      lmerTest::lmer(y ~ z + (1 | participant_id) + (1 | question_id), data = d)
    broom.mixed::tidy(m, effects = "fixed", conf.int = TRUE) %>%
      filter(term == "z")
  }) %>% ungroup()

# per-experiment total-StP coefficients: is the aggregate effect just pooled n?
# (common z-scaling across the E1-E3 sample so slopes are comparable)
stp_exp_dat <- stp_disagree %>%
  mutate(z = as.numeric(scale(stp))) %>%
  select(experiment, participant_id, question_id, persuader_success,
         confidence_change, z)
stp_exp <- bind_rows(stp_exp_dat,
                     stp_exp_dat %>% mutate(experiment = "Pooled")) %>%
  pivot_longer(c(persuader_success, confidence_change),
               names_to = "measure", values_to = "y") %>%
  mutate(measure = factor(measure, c("persuader_success", "confidence_change"),
                          c("Persuader success (log-odds per SD)",
                            "Confidence change (points per SD)"))) %>%
  group_by(measure, experiment) %>%
  group_modify(function(d, g) {
    m <- if (grepl("success", g$measure))
      lme4::glmer(y ~ z + (1 | participant_id) + (1 | question_id),
                  family = binomial, data = d, control = GLMER_CTRL)
    else
      lmerTest::lmer(y ~ z + (1 | participant_id) + (1 | question_id), data = d)
    broom.mixed::tidy(m, effects = "fixed", conf.int = TRUE) %>%
      filter(term == "z")
  }) %>% ungroup()
message("per-experiment total-StP coefficients (disagree trials):")
print(as.data.frame(stp_exp %>%
  select(measure, experiment, estimate, conf.low, conf.high, p.value)))

LAB_PS_PP <- "Persuader success (pp per SD)"
LAB_CC_PT <- "Confidence change (points per SD)"
stp_coefs <- read.csv("stats/stp_coefs.csv")
stp_long_coefs <- bind_rows(
  stp_coefs %>% transmute(set, label, measure = LAB_PS_PP, estimate = ps_pp,
                          conf.low = ps_pp_lo, conf.high = ps_pp_hi),
  stp_coefs %>% transmute(set, label, measure = LAB_CC_PT, estimate = cc_b,
                          conf.low = cc_lo, conf.high = cc_hi)
) %>% mutate(measure = factor(measure, c(LAB_PS_PP, LAB_CC_PT)))
stp_exp_csv <- stp_long_coefs %>% filter(set == "experiment") %>% rename(experiment = label)
# reverse-coded subscales: plain names + dagger, explained in the panel caption
REV_LABELS <- c("Low need for cognition" = "Need for cognition\u2020",
                "Low premeditation"      = "Premeditation\u2020",
                "Low self-control"       = "Self-control\u2020")
forest_csv  <- stp_long_coefs %>% filter(set == "subscale") %>% rename(category = label) %>%
  mutate(category = ifelse(category %in% names(REV_LABELS), REV_LABELS[category], category))
ii7 <- ggplot(stp_exp_csv,
              aes(estimate, factor(experiment, rev(c("E1", "E2", "E3", "Pooled"))),
                  xmin = conf.low, xmax = conf.high,
                  color = experiment == "Pooled")) +
  geom_vline(xintercept = 0, linetype = "dashed", linewidth = 0.3, color = "grey50") +
  geom_pointrange(size = 0.4, linewidth = EB_LINEWIDTH) +
  scale_color_manual(values = c(`TRUE` = "#4477AA", `FALSE` = "grey25"),
                     guide = "none") +
  facet_wrap(~measure, scales = "free_x") +
  labs(x = "Effect per SD of total StP-II (95% CI)", y = NULL) +
  theme_paper
save_png("ii7_stp_total_byexp", ii7, w = 6.5, h = 2.2)

ii6 <- ggplot(forest_csv,
              aes(estimate, reorder(category, estimate),
                  xmin = conf.low, xmax = conf.high,
                  color = category == "Total StP-II")) +
  geom_vline(xintercept = 0, linetype = "dashed", linewidth = 0.3, color = "grey50") +
  geom_pointrange(size = 0.4, linewidth = EB_LINEWIDTH) +
  scale_color_manual(values = c(`TRUE` = "#4477AA", `FALSE` = "grey25"),
                     guide = "none") +
  facet_wrap(~measure, scales = "free_x") +
  labs(x = "Effect per SD of subscale (95% CI)", y = NULL, subtitle = "Disagreement Trials Only") +
  theme_paper
save_png("ii6_stp_forest", ii6, w = 6.5, h = 3.2)

# =============================================================================
# (iii) by-question
# =============================================================================
message("family iii: by-question")

# dagger rendered small via ggtext markdown (needs element_markdown on the axis)
dagger <- function(name)
  ifelse(name %in% E4_REMOVED,
         paste0(name, "<span style='font-size:",
                BASE_SIZE - 4, "pt'>†</span>"),
         name)

q_ease <- disagree %>% group_by(subcategory, name) %>%
  summarize(ps = mean(persuader_success), n = n(),
            lo = ci_fun(persuader_success)$ymin,
            hi = ci_fun(persuader_success)$ymax, .groups = "drop") %>%
  mutate(name = dagger(name))

iii1 <- ggplot(q_ease, aes(ps, reorder(name, ps), color = subcategory)) +
  geom_errorbarh(aes(xmin = lo, xmax = hi), height = 0, linewidth = EB_LINEWIDTH) +
  geom_point(size = 1.8) +
  scale_color_manual(name = "Topic", values = PAL_TOPIC2) +
  scale_x_continuous(labels = scales::percent) +
  labs(x = LAB_PS, y = NULL, subtitle = "Disagreement Trials Only (pooled E1-E4)") +
  theme_paper +
  theme(axis.text.y = element_markdown(size = BASE_SIZE - 2),
        panel.grid.major.y = element_blank())
save_png("iii1_q_ease_dots", iii1, w = 5.0, h = 5.6)

iii1b <- ggplot(q_ease, aes(ps, reorder(name, ps), fill = subcategory)) +
  geom_col(width = 0.72, color = "white", linewidth = 0.3) +
  geom_errorbarh(aes(xmin = lo, xmax = hi), height = 0.25,
                 linewidth = EB_LINEWIDTH, color = "grey25") +
  scale_fill_manual(name = "Topic", values = PAL_TOPIC) +
  scale_x_continuous(labels = scales::percent) +
  labs(x = LAB_PS, y = NULL, subtitle = "Disagreement Trials Only (pooled E1-E4)") +
  theme_paper +
  theme(axis.text.y = element_markdown(size = BASE_SIZE - 2),
        panel.grid.major.y = element_blank())
save_png("iii1b_q_ease_bars", iii1b, w = 5.0, h = 5.6)

q_truth <- disagree %>% group_by(subcategory, name, truth) %>%
  summarize(ps = mean(persuader_success), n = n(), .groups = "drop") %>%
  group_by(name) %>% filter(n() == 2, min(n) >= 10) %>%
  mutate(adv = ps[truth == "Truth"] - ps[truth == "Falsehood"]) %>% ungroup() %>%
  mutate(name = dagger(name))

# dumbbell: PS arguing truth vs falsehood, per question, sorted by advantage
iii2 <- ggplot(q_truth, aes(ps, reorder(name, adv))) +
  geom_line(aes(group = name), color = "grey60", linewidth = 0.5) +
  geom_point(aes(color = truth), size = 1.8) +
  scale_color_manual(name = LAB_TRUTH, values = PAL_TRUTH) +
  scale_x_continuous(labels = scales::percent) +
  labs(x = LAB_PS, y = NULL,
       subtitle = "Disagreement Trials Only; cells with n >= 10") +
  theme_paper +
  theme(axis.text.y = element_markdown(size = BASE_SIZE - 2),
        panel.grid.major.y = element_blank())
save_png("iii2_q_truth_dumbbell", iii2, w = 5.0, h = 5.6)

# diverging bars of the advantage itself
iii3 <- q_truth %>% distinct(subcategory, name, adv) %>%
  ggplot(aes(adv, reorder(name, adv), fill = adv > 0)) +
  geom_col(width = 0.72, color = "white", linewidth = 0.3) +
  geom_vline(xintercept = 0, linewidth = 0.3, color = "grey50") +
  scale_fill_manual(values = c(`TRUE` = "#4477AA", `FALSE` = "#EE6677"),
                    guide = "none") +
  scale_x_continuous(labels = scales::percent) +
  labs(x = "Truth advantage (PS truth - PS falsehood)", y = NULL,
       subtitle = "Disagreement Trials Only; cells with n >= 10") +
  theme_paper +
  theme(axis.text.y = element_markdown(size = BASE_SIZE - 2),
        panel.grid.major.y = element_blank())
save_png("iii3_q_truth_advbars", iii3, w = 5.0, h = 5.6)

# scatter: PS truth vs PS falsehood (diagonal = no advantage)
iii4 <- q_truth %>%
  select(subcategory, name, truth, ps) %>%
  pivot_wider(names_from = truth, values_from = ps) %>%
  ggplot(aes(Falsehood, Truth, color = subcategory)) +
  geom_abline(linetype = "dashed", linewidth = 0.3, color = "grey50") +
  geom_point(size = 2) +
  ggrepel::geom_text_repel(aes(label = name), size = 2.3, max.overlaps = 8,
                           show.legend = FALSE) +
  scale_color_manual(name = "Topic", values = PAL_TOPIC) +
  scale_x_continuous(labels = scales::percent, limits = c(0, 1)) +
  scale_y_continuous(labels = scales::percent, limits = c(0, 1)) +
  labs(x = "PS when arguing falsehood", y = "PS when arguing truth",
       subtitle = "Disagreement Trials Only; cells with n >= 10") +
  theme_paper
save_png("iii4_q_truth_scatter", iii4, w = 4.6, h = 4.6)

# stability check: advantage by experiment-family (E1/E2 vs E3 vs E4)
q_truth_exp <- disagree %>%
  mutate(expgrp = case_when(experiment %in% c("E1", "E2") ~ "E1+E2",
                            TRUE ~ experiment)) %>%
  group_by(expgrp, name, truth) %>%
  summarize(ps = mean(persuader_success), n = n(), .groups = "drop") %>%
  group_by(expgrp, name) %>% filter(n() == 2, min(n) >= 8) %>%
  summarize(adv = ps[truth == "Truth"] - ps[truth == "Falsehood"],
            .groups = "drop")
iii5 <- ggplot(q_truth_exp, aes(adv, reorder(name, adv))) +
  geom_col(width = 0.72, fill = "grey35") +
  geom_vline(xintercept = 0, linewidth = 0.3, color = "grey50") +
  facet_grid(. ~ expgrp) +
  scale_x_continuous(labels = scales::percent) +
  labs(x = "Truth advantage", y = NULL, subtitle = "cells with n >= 8") +
  theme_paper +
  theme(axis.text.y = element_text(size = BASE_SIZE - 2.5),
        panel.grid.major.y = element_blank())
save_png("iii5_q_truth_byexp", iii5, w = 6.5, h = 5.6)

# =============================================================================
# recommended assemblies
# =============================================================================
message("recommended assemblies")

# (i) one row: overall pooled | truth x confidence | E4 persuader type
rec_i <- (
  (i1 + labs(title = "Overall", subtitle = "Pooled E1-E4", x = NULL)) |
  (i3 + labs(title = "By truth", subtitle = "Pooled E1-E4", y = NULL)) |
  (i5b + labs(title = "By persuader", subtitle = "E4 Only", x = NULL, y = NULL))
) +
  plot_layout(guides = "collect") +
  plot_annotation(tag_levels = "a",
                  caption = "Disagreement trials only") &
  theme(legend.position = "bottom", legend.justification = "center",
        legend.spacing.x = unit(30, "pt"),
        plot.caption = element_text(size = BASE_SIZE - 3.5, color = "grey45",
                                    hjust = 0.5))
save_png("REC_i_confidence", rec_i, w = 6.5, h = 3.4)

# (ii) rows: total StP vs PS and CC / per-experiment forest / subscale forest.
# free() exempts the scatter row from patchwork's global axis alignment --
# otherwise the forests' long y labels push a/b rightward, stranding dead
# space on the left.
rec_ii <- (
  free((ii1b + labs(title = "Persuader success", subtitle = "Disagreement Trials Only (E1-E3)")) |
     (ii2b + labs(title = "Confidence change", subtitle = "Disagreement Trials Only (E1-E3)"))) /
  free(ii7 + labs(title = "Total StP by experiment")) /
  (ii6 + labs(title = "Subscales (pooled E1-E3)", subtitle = NULL,
              caption = "\u2020 Reverse coded: higher scores indicate lower need for cognition, premeditation, and self-control.") +
     theme(plot.caption = element_text(size = BASE_SIZE - 3, color = "grey45", hjust = 0)))
) +
  plot_layout(heights = c(1, 0.5, 1.1)) +
  plot_annotation(tag_levels = "a")
save_png("REC_ii_stp", rec_ii, w = 6.5, h = 8.6)
save_pdf("xp_stp", rec_ii, w = 6.5, h = 8.6)

# (iii) ease of persuasion | truth advantage bars; dagger = dropped from E4
rec_iii <- (
  (iii1 + labs(subtitle = "Overall persuasion rate")) |
  (iii3 + labs(subtitle = "By truth of the persuader's position"))
) +
  plot_annotation(tag_levels = "a",
                  caption = "Disagreement trials only, pooled E1-E4. † question not included in E4.") &
  theme(legend.position = "bottom", legend.justification = "center",
        plot.caption = element_text(size = BASE_SIZE - 3.5, color = "grey45",
                                    hjust = 0.5))
save_png("REC_iii_questions", rec_iii, w = 6.5, h = 5.8)
save_pdf("xp_questions", rec_iii, w = 6.5, h = 5.8)

message("family iv: asymmetry")
LAB_SIDE <- "Participant initially"
PAL_SIDE <- c("Incorrect" = unname(PAL_TRUTH["Truth"]), "Correct" = unname(PAL_TRUTH["Falsehood"]))
side_lab <- c("Incorrect" = "Incorrect (persuader argues truth)",
              "Correct"   = "Correct (persuader argues falsehood)")
asym_curves <- read.csv("stats/qual_truth_conf_curves.csv") %>%
  mutate(side = factor(ifelse(persuader_correct, "Incorrect", "Correct"), names(PAL_SIDE)))
asym_obs <- disagree %>%
  filter(persuader_type == "LLM", is.na(hint_condition) | hint_condition != "Hint",
         (experiment != "E3" & trial_type == "final") | (trial_type == "intro" & trial_index == 0)) %>%
  mutate(side = factor(ifelse(persuader_correct, "Incorrect", "Correct"), names(PAL_SIDE)),
         bin = floor(pmin(confidence_pre, 99) / 25) * 25 + 12.5) %>%
  group_by(side, bin) %>%
  summarize(ps = 100 * mean(persuader_success), cc = mean(confidence_change), n = n(), .groups = "drop")
message("asymmetry obs n = ", sum(asym_obs$n))
asym_panel <- function(y, lo, hi, oy, ylab, title) {
  ggplot() +
    geom_ribbon(data = asym_curves, aes(confidence, ymin = .data[[lo]], ymax = .data[[hi]], fill = side),
                alpha = 0.18) +
    geom_line(data = asym_curves, aes(confidence, .data[[y]], color = side, linetype = side),
              linewidth = LINE_WIDTH) +
    geom_point(data = asym_obs, aes(bin, .data[[oy]], color = side, size = n), alpha = 0.75) +
    scale_color_manual(name = LAB_SIDE, values = PAL_SIDE, labels = side_lab) +
    scale_fill_manual(name = LAB_SIDE, values = PAL_SIDE, labels = side_lab) +
    scale_linetype_manual(name = LAB_SIDE, values = c("Incorrect" = "solid", "Correct" = "dashed"),
                          labels = side_lab) +
    scale_size_area(max_size = 4, guide = "none") +
    scale_x_continuous(breaks = seq(0, 100, 25)) +
    labs(x = LAB_CONF, y = ylab, title = title) +
    theme_paper
}
asym_a <- asym_panel("ps", "ps_lo", "ps_hi", "ps", "Persuader success (%)", "Persuader success") +
  coord_cartesian(ylim = c(40, 100))
asym_b <- asym_panel("cc", "cc_lo", "cc_hi", "cc", "Confidence change", "Confidence change") +
  coord_cartesian(ylim = c(0, 100))
asym <- (asym_a | asym_b) + plot_layout(guides = "collect") +
  plot_annotation(tag_levels = "a") &
  theme(legend.position = "bottom", legend.justification = "center")
save_png("xp_truth_asym", asym, w = 6.5, h = 3.4)

message("done: ", OUT)
