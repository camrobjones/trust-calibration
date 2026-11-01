# Data dictionary

## conversation_Participant.csv

One row per participant.

| Column | Meaning |
|---|---|
| `id` | Participant ID |
| `sona_code` | Blank, except `test` and `131`, which mark experimenter test sessions |
| `source`, `study` | Recruitment source and experiment. In Experiment 4, a blank `source` is the undergraduate subject pool |
| `start_time`, `end_time`, `last_updated` | Session timestamps |
| `status` | `completed`, `incomplete`, `abandoned`, `partner_abandoned` |
| `birth_year`, `gender`, `native_english` | Self-reported. `gender`: `f`, `m`, `nb`, `na`. `birth_year` is unvalidated and includes implausible entries |
| `physics`, `logic`, `ethics`, `policy`, `probability` | Self-rated expertise, 1 to 5 |
| `model_persuasiveness`, `model_likeability`, `model_reliability` | Exit ratings of the advisor, 1 to 7. The paper labels these Persuasive, Likeable, Reliable; the reliability item asks how likely the participant would be to follow the advisor's advice |
| `model_error_rate`, `model_incorrect_training`, `model_incorrect_instruction` | Exit ratings, 1 to 7. The paper labels these Incorrect, Mistaken, Deceptive |
| `model_incorrect_open` | Free text about advisor errors |
| `advisor_type`, `advisor_confidence`, `advisor_reasoning` | Experiment 4: judged human or AI, confidence 1 to 7, free-text reason |
| `intro_condition` | 1 Helpful, 0 Mixed, -1 Unhelpful |
| `final_condition` | 1 Helpful, -1 Unhelpful (final trial) |
| `feedback_condition` | 1 Feedback, 0 No feedback |
| `hint_condition` | 0 Interactive conversation, 1 Static hint |
| `n_survey_questions`, `n_persuadability_questions`, `n_conversations`, `questions_balanced` | Session configuration |
| `consulted`, `sources` | Reported using outside sources; free-text description |
| `debrief` | Free-text debrief |
| `interaction_type` | `human_ai` or `human_human` |
| `is_timeout_match` | True if the participant was moved to an AI partner after a waiting-room timeout |

## conversation_Conversation.csv

One row per trial.

| Column | Meaning |
|---|---|
| `id`, `participant_id` | Conversation ID and the decision-maker's participant ID |
| `ai_persuader_id` | Row in `conversation_AIPersuader.csv`. Blank for Experiments 1 to 3; `e1.Rmd` and `e2.Rmd` set it to 2 (GPT-4.5) directly |
| `human_persuader_id` | Participant ID of the human advisor (Experiment 4) |
| `persuader_is_human` | True if the advisor was a person |
| `question_id` | Row in `conversation_Question.csv` |
| `trial_index`, `trial_type` | Position within the session (0 to 4) and `intro` or `final` |
| `persuader_answer`, `target_answer`, `correct_answer` | `answer1` or `answer2` |
| `start_time`, `end_time` | Timestamps. `end_time` is unreliable as a duration, so scripts compute duration from message timestamps |
| `status` | Software state: `created`, `verdict`, `skipped`, `finished` |

## conversation_Message.csv

One row per chat message.

| Column | Meaning |
|---|---|
| `id`, `conversation_id` | Message ID and conversation ID |
| `sender_role` | `T` target (decision-maker) or `P` persuader (advisor) |
| `content` | Message text |
| `timestamp` | Send time |
| `cost` | API cost in US dollars |

## conversation_QuestionResponse.csv

One row per answer.

| Column | Meaning |
|---|---|
| `id`, `participant_id`, `question_id`, `trial_index` | Identifiers |
| `created` | Timestamp |
| `response_type` | `pre` (before the conversation) or `post` (after it) |
| `response` | The answer text |
| `confidence` | 0 to 100, confidence in the chosen answer (0 = guessing) |
| `agreement` | Unused; always blank |
| `reason` | Free text |
| `reaction_time` | Milliseconds |

## conversation_PersuadabilityResponse.csv

Susceptibility to Persuasion II items. Columns: `id`, `participant_id`, `question_id`, `created`,
`response` (1 to 7), `scoring` (1, or -1 for reverse-scored items), `reaction_time` (ms).
No Experiment 4 participant has rows here; the block was configured but never served.

## Materials tables

- `conversation_Question.csv`: the 33 questions used, including attention checks, with `category`,
  `subcategory`, `name`, `question`, `answer1`, `answer2`, `correct_answer`.
- `conversation_PersuadabilityQuestion.csv`: scale items, subscales, and scoring.
- `conversation_AIPersuader.csv`: advisor configurations. Row 2 is GPT-4.5 (Experiments 1 to 3) and
  row 5 is GPT-5 (Experiment 4). `prompt` is the system prompt. `temperature` and `max_length` are
  stored settings; `experiment_code/conversation/models.py` shows how each was applied.

## tags/ and corrigibility_tags.csv

LLM codings of the conversations, all keyed on `conversation_id`. Values are 1 if the category is
present and 0 if not, unless stated.

| File | Contents |
|---|---|
| `final_ratings.csv` + `final_ratings_addendum.csv` | The 15 final categories, whole conversation. The addendum covers 216 conversations missed by the first run, tagged with the same pipeline |
| `final_ratings_raw.csv` + `final_ratings_raw_addendum.csv` | The 26 individual strategies behind those categories |
| `first_message_ratings.csv`, `first_message_ratings_raw.csv` | The same tagger on transcripts cut after the persuader's first message (`fm_` prefix) |
| `position_compliance.csv` | Whether the persuader argued the assigned position: `compliance` (`advocated`, `abandoned`, `never_advocated`, `argued_opposite`), `final_position`, `disclosed_assignment`, and an `evidence` quote |
| `human_ratings.csv` | Two human raters' ratings of the 141 validation conversations (`rater1`, `rater2`), used by `analysis/irr.py` |
| `../corrigibility_tags.csv` | Earlier concession coding of LLM conversations, Experiments 1 to 3 (`Yes`, `No`, `Unclear`). Kept because `e3.Rmd` and `qualitative_tags.Rmd` compare against it |

`tagging/CODEBOOK.md` defines every strategy.

## item_difficulty.csv

`question_id`, `n_answers`, `n_correct`. Counts of all pre-conversation answers to each item across the
whole database, including pilots and another study that are not released. `qualitative_tags.Rmd` uses
these for its item-difficulty covariate, `p_wrong = 1 - n_correct / n_answers`.

## analysis/stats/

Files the scripts generate, so they are not needed as input. The most useful for checking are:

- `eX_trials.csv`: one row per analyzed trial, with harmonized columns (`persuader_success`,
  `confidence_change`, `persuader_correct`, `participant_persuader_disagree`, and so on)
- `eX_survey.csv`, `eX_exit_survey.csv`: survey and exit ratings
- `eX_stats.csv`: tidy model results (`hypothesis`, `measure`, `term`, `b`, `se`, `stat_type`, `stat`, `df`, `p`, `n`)
- `eX_descriptives.csv`: final-trial means by condition

## De-identification

Direct data identifiers have been removed, and PII included in participant free-text has been masked with strings of `X` the same length as the original.