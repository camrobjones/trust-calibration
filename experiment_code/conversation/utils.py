"""Utility functions for conversation app."""

import random
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import requests
import pandas as pd

from conversation.models import Question, QuestionResponse, PersuadabilityQuestion

SONA_URL = "https://REDACTED.sona-systems.com/services/SonaAPI.svc/WebstudyCredit"
SONA_EXPT_ID = "REDACTED"
SONA_CREDIT_TOKEN = "REDACTED"


def load_survey_questions(n=None):

    survey_questions = Question.objects.filter(
        category__in=["objective", "attention_check"]
    ).order_by("?")[:n]

    survey_questions = [
        {
            "id": q.id,
            "question": q.question,
            "answer1": q.answer1,
            "answer2": q.answer2,
            "correct_answer": q.correct_answer,
            "category": q.category,
        }
        for q in survey_questions
    ]

    return survey_questions


def load_persuadability_questions(n=None):

    persuadability_questions = PersuadabilityQuestion.objects.order_by("?")[:n]

    persuadability_questions = [
        {
            "id": q.item_id,
            "question": q.question,
            "category": q.category,
            "subcategory": q.subcategory,
            "scoring": q.scoring,
        }
        for q in persuadability_questions
    ]

    return persuadability_questions


def check_credit_granted(sona_response):
    """Parse SONA XML response and check if credit granted."""
    sona = "http://schemas.datacontract.org/2004/07/emsdotnet.sonasystems"
    namespace = {"sona": sona}

    try:
        root = ET.fromstring(sona_response)
        result = root[0].find("sona:Result", namespace)
        credit_granted = result.find("sona:credit_status", namespace).text
        if credit_granted == "G":
            return True

    except:
        pass

    return False


def grant_credit(ppt):
    """Attempt to grant SONA credit to participant."""
    # https://REDACTED.sona-systems.com/webstudy_credit.aspx?experiment_id=REDACTED&credit_token=&survey_code=XXXX

    # Build SONA Web Credit URL
    params = {
        "experiment_id": SONA_EXPT_ID,
        "credit_token": SONA_CREDIT_TOKEN,
        "survey_code": ppt.sona_code,
    }
    url = f"{SONA_URL}?{urlencode(params)}"

    # Send request & parse content
    response = requests.get(url, timeout=5)
    content = response.content.decode()
    ppt.notes = ppt.notes + f"\nSONA credit response:\n{content}\n"

    if check_credit_granted(content):
        return True

    return False


def generate_questions_for_participant(ppt):
    """
    Generate a set of questions for a participant based on their stored conditions and DB responses,
    returning a list of dicts (one per trial). Conditions are read from the Participant instance.
    """
    # Get participant and condition info
    # ppt = Participant.objects.get(id=participant_id)
    intro_cond = ppt.intro_condition  # 1, 0, or -1
    final_cond = ppt.final_condition  # 1 or -1
    sycophancy_cond = ppt.sycophancy_condition

    intro_label = (
        ppt.get_intro_condition_display()
    )  # e.g. "Helpful", "Neutral", "Unhelpful"
    final_label = ppt.get_final_condition_display()  # e.g. "Participant Correct", etc.
    sycophancy_label = (
        ppt.get_sycophancy_condition_display()
    )  # e.g. "Sycophancy", "Mixed", "Anti-Sycophancy"
    # Load responses into a DataFrame
    responses = pd.DataFrame(
        list(
            QuestionResponse.objects.filter(participant=ppt).values(
                "question__id", "response", "confidence"
            )
        )
    )
    if responses.empty:
        raise ValueError(f"No responses found for participant {ppt}")

    responses = responses.rename(
        columns={"question__id": "item_id", "response": "response"}
    ).sort_values(by="item_id")
    responses["item_id"] = responses["item_id"].astype(int)

    # Load questions from CSV and filter by category
    questions = pd.DataFrame(load_survey_questions())
    questions = questions[questions.category == "objective"]
    questions = questions.rename(columns={"id": "item_id", "question": "name"})

    # Merge responses with question info
    merged = responses.merge(questions, on="item_id", how="inner")
    merged["response_code"] = merged.apply(
        lambda x: "answer1" if x["response"] == x["answer1"] else "answer2", axis=1
    )
    merged["accuracy"] = merged.apply(
        lambda x: 1 if x["response_code"] == x["correct_answer"] else 0, axis=1
    )
    merged["confidence"] = merged["confidence"].fillna(0)

    # Split into correct and wrong responses
    correct = merged[merged["accuracy"] == 1]
    wrong = merged[merged["accuracy"] == 0]
    imbalanced = len(correct) < 3 or len(wrong) < 3
    ppt.questions_balanced = not imbalanced
    ppt.save()

    # Randomly select rank (0, 1, or 2) from top 3 most confident
    selected_rank = random.randint(0, 2)

    # For final trial: select randomly chosen rank based on condition
    if final_cond == 1:
        # Model should be correct, so pick from wrong responses
        final = (
            wrong.nlargest(3, "confidence")
            .iloc[selected_rank : selected_rank + 1]
            .copy()
        )
        final["model_correct"] = "correct_answer"

        # For intro trials: remove same rank from opposite group to balance confidence
        available_ranks = [i for i in range(3) if i != selected_rank]
        intro_correct = correct.nlargest(3, "confidence").iloc[available_ranks].copy()
        intro_incorrect = wrong.nlargest(3, "confidence").iloc[available_ranks].copy()

    elif final_cond == -1:
        # Model should be incorrect, so pick from correct responses
        final = (
            correct.nlargest(3, "confidence")
            .iloc[selected_rank : selected_rank + 1]
            .copy()
        )
        final["model_correct"] = "incorrect_answer"

        # For intro trials: remove same rank from opposite group to balance confidence
        available_ranks = [i for i in range(3) if i != selected_rank]
        intro_correct = correct.nlargest(3, "confidence").iloc[available_ranks].copy()
        intro_incorrect = wrong.nlargest(3, "confidence").iloc[available_ranks].copy()

    else:
        raise ValueError("final_condition must be 1 or -1.")

    # Combine intro trials and shuffle
    intro = pd.concat([intro_correct, intro_incorrect])

    # Override model correctness based on intro condition
    if intro_cond == 1:
        intro["model_correct"] = "correct_answer"
    elif intro_cond == -1:
        intro["model_correct"] = "incorrect_answer"
    elif intro_cond == 0:
        # For neutral condition, randomly assign correctness
        if sycophancy_cond == 1:
            # Sycophancy condition: agrees 100% of the time
            intro["model_correct"] = [
                "correct_answer" if x else "incorrect_answer" for x in intro["accuracy"]
            ]
        elif sycophancy_cond == 0:
            # Mixed condition: agrees 50% of the time
            if random.random() < 0.5:
                intro["model_correct"] = ["correct_answer", "incorrect_answer"] * 2
            else:
                intro["model_correct"] = ["incorrect_answer", "correct_answer"] * 2
        elif sycophancy_cond == -1:
            # Anti-sycophancy condition: disagrees 100% of the time
            intro["model_correct"] = [
                "incorrect_answer" if x else "correct_answer" for x in intro["accuracy"]
            ]
        else:
            raise ValueError("sycophancy_condition must be 1 or 0.")

    else:
        raise ValueError("intro_condition must be 1, 0, or -1.")

    intro = intro.sample(frac=1).reset_index(drop=True)

    intro["trial_type"] = "intro"
    final["trial_type"] = "final"

    trials_df = pd.concat([intro, final], ignore_index=True)

    # Given the correct_answer, define model_answer (swap answer1 <-> answer2)
    def assign_model_answer(row):
        swap = {"answer1": "answer2", "answer2": "answer1"}
        if row["model_correct"] == "correct_answer":
            return row["correct_answer"]
        else:
            return swap.get(row["correct_answer"])

    trials_df["model_answer"] = trials_df.apply(assign_model_answer, axis=1)
    trials_df["intro_condition"] = intro_label
    trials_df["final_condition"] = final_label
    trials_df["sycophancy_condition"] = sycophancy_label
    # Concatenate and return as list of dicts

    return trials_df.to_dict(orient="records")
