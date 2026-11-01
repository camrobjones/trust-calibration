"""Views for the conversation app."""

import json
import os
import random

import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.utils import timezone as tz
from django.contrib.auth.decorators import user_passes_test
import pandas as pd
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from django.db import models
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from conversation.models import (
    Participant,
    QuestionResponse,
    Conversation,
    AIPersuader,
    Message,
    Question,
    PersuadabilityQuestion,
    PersuadabilityResponse,
)
from conversation import utils

# Constants

MODULE_URL = "conversation"
MODELS = {
    "Participant": Participant,
    "QuestionResponse": QuestionResponse,
    "Conversation": Conversation,
    "AIPersuader": AIPersuader,
    "Message": Message,
    "Question": Question,
    "PersuadabilityQuestion": PersuadabilityQuestion,
    "PersuadabilityResponse": PersuadabilityResponse,
}

SONA_URL = "https://REDACTED.sona-systems.com/services/SonaAPI.svc/WebstudyCredit"
SONA_EXPT_ID = "REDACTED"
SONA_CREDIT_TOKEN = "REDACTED"

# Optional Prolific completion URL (e.g., https://app.prolific.com/submissions/complete?cc=REDACTED)
PROLIFIC_COMPLETION_URL = "https://app.prolific.com/submissions/complete?cc=REDACTED"

# Views


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

    except Exception:
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


def survey(request):
    """Server the main survey page."""
    n_survey_questions = int(request.GET.get("n_survey_questions", 33))
    n_persuadability_questions = int(request.GET.get("n_persuadability_questions", 30))
    n_conversations = request.GET.get("n_conversations", 5)
    study = request.GET.get("study", "4")
    prolific_id = request.GET.get("PROLIFIC_PID", None)

    if study == "test":
        intro_cond = 1
        final_cond = -1
        feedback_cond = 1
        interaction_type = "human_ai"
        sycophancy_cond = 0
        hint_cond = 0

    elif study == "4":
        intro_cond = int(request.GET.get("intro_condition", random.choice([0, 1])))
        final_cond = int(request.GET.get("final_condition", random.choice([-1, 1])))
        feedback_cond = 1
        hint_cond = 0
        interaction_type = request.GET.get(
            "interaction_type",
            # "human_ai" if random.random() > 0.925 else "human_human",
            "human_human",
        )
        sycophancy_cond = 0

    elif study == "5":

        condition = request.GET.get("condition", random.choice([1, 2, 3]))
        if condition == 1:
            intro_cond = 1
            sycophancy_cond = 0
        if condition == 2:
            intro_cond = 0
            sycophancy_cond = 0
        if condition == 3:
            intro_cond = 0
            sycophancy_cond = 1

        final_cond = int(request.GET.get("final_condition", random.choice([-1, 1])))
        feedback_cond = 0
        hint_cond = 0
        interaction_type = "human_ai"
    else:
        raise ValueError(f"Invalid study: {study}")

    sona_code = request.GET.get("code")
    source = request.GET.get("source")

    ppt = Participant.objects.create(
        study=study,
        sona_code=sona_code,
        prolific_id=prolific_id,
        source=source,
        intro_condition=intro_cond,
        final_condition=final_cond,
        feedback_condition=feedback_cond,
        hint_condition=hint_cond,
        n_survey_questions=n_survey_questions,
        n_persuadability_questions=n_persuadability_questions,
        n_conversations=n_conversations,
        interaction_type=interaction_type,
        sycophancy_condition=sycophancy_cond,
    )

    survey_questions = utils.load_survey_questions(n_survey_questions)

    conf = {
        "survey_questions": survey_questions,
        "n_conversations": n_conversations,
        "ppt_id": ppt.id,
        "source": source,
        "study": study,
    }
    context = {"conf": conf}
    return render(request, "conversation/survey.html", context)


def create_ppt_conversations(ppt):
    """Create conversation objects for a participant."""
    n_conversations = ppt.n_conversations or 5
    questions = utils.generate_questions_for_participant(ppt)

    questions = questions[:n_conversations]

    # Change to select a random persuader
    persuader = AIPersuader.objects.filter(active=True).order_by("?").first()

    for i, q in enumerate(questions):
        question = Question.objects.get(id=q["item_id"])
        Conversation.objects.create(
            participant=ppt,
            ai_persuader=persuader,
            question=question,
            trial_index=i,
            trial_type=q["trial_type"],
            persuader_answer=q["model_answer"],
            target_answer=q["response_code"],
            correct_answer=q["correct_answer"],
        )


def save_survey_results(request):
    """Save survey results to database."""
    post = json.loads(request.body.decode("utf-8"))
    data = post["results"]
    ppt_id = post["ppt_id"]

    # Get or create participant object
    ppt, _ = Participant.objects.get_or_create(id=ppt_id)

    critical_trials = [item for item in data if item.get("item_type") == "critical"]

    for ct in critical_trials:
        response = ct.get("response")
        question = Question.objects.get(id=ct.get("item_id"))
        QuestionResponse.objects.create(
            participant=ppt,
            question=question,
            trial_index=ct.get("trial_index"),
            response=response.get("answer"),
            confidence=response.get("confidence"),
            reaction_time=ct.get("rt"),
        )

    ppt.save()

    create_ppt_conversations(ppt)

    return JsonResponse({"success": True})


def conversation_instructions(request):
    """Render conversation instructions."""
    ppt_id = request.GET.get("ppt_id")
    ppt = Participant.objects.get(id=ppt_id)
    hint_cond = ppt.hint_condition
    interaction_type = ppt.interaction_type

    return render(
        request,
        "conversation/conversation_instructions.html",
        {
            "ppt_id": ppt_id,
            "hint_cond": hint_cond,
            "interaction_type": interaction_type,
        },
    )


def conversation(request):
    """Render participant conversation"""
    ppt_id = request.GET.get("ppt_id")
    # Validate ppt_id; redirect to survey if missing/invalid
    try:
        if ppt_id is None:
            return redirect("/conversation/survey/")
        int(ppt_id)
    except Exception:
        return redirect("/conversation/survey/")

    ppt = Participant.objects.get(id=ppt_id)
    # Fetch conversations where this participant is either the target or human persuader
    conversations = Conversation.objects.filter(
        models.Q(participant=ppt) | models.Q(human_persuader=ppt)
    )
    # Use status-based selection: consider created/started/finished as eligible
    next_conv = (
        conversations.filter(status__in=["created", "started", "finished"])
        .order_by("trial_index")
        .first()
    )

    if next_conv is None:
        return redirect("exit_survey", ppt_id=ppt_id)

    # if convo has not started, set start time to now
    if next_conv.start_time is None:
        next_conv.start_time = tz.now()
        next_conv.status = "started"
        next_conv.save(update_fields=["start_time", "status"])

    # calculate time remaining
    start_time = next_conv.start_time
    elapsed_time = int((tz.now() - start_time).total_seconds()) if start_time else 0
    time_remaining = max(300 - elapsed_time, 0)

    # Get messages for convo
    messages = Message.objects.filter(conversation=next_conv).order_by("timestamp")
    messages = [{"role": m.sender_role, "message": m.content} for m in messages]

    # If time has fully elapsed and the conversation isn't marked ended yet, close it now (idempotent)
    if time_remaining <= 0 and next_conv.end_time is None:
        next_conv.end_time = tz.now()
        next_conv.status = "finished"
        next_conv.save(update_fields=["end_time", "status"])

    next_conv_data = {
        "id": next_conv.id,
        "question_id": next_conv.question.id,
        "trial_index": next_conv.trial_index,
        "trial_type": next_conv.trial_type,
        "time_remaining": time_remaining,
        "messages": messages,
        "correct_answer": next_conv.correct_answer,
        "persuader_answer": next_conv.persuader_answer,
    }

    question = next_conv.question
    question_data = {
        "question": question.question,
        "answer1": question.answer1,
        "answer2": question.answer2,
    }

    # Determine role for this participant
    role = "T" if next_conv.participant_id == ppt.id else "P"

    context = {
        "ppt_id": ppt_id,
        "feedback_cond": ppt.feedback_condition,
        "hint_cond": ppt.hint_condition,
        "role": role,
        "conversation": next_conv_data,
        "question": question_data,
    }

    # Route to different templates based on hint_condition
    template_name = (
        "conversation/conversation_static.html"
        if ppt.hint_condition == 1
        else "conversation/conversation.html"
    )

    return render(request, template_name, {"context": context})


@require_http_methods(["GET"])
def get_messages(request):
    """Get current message history for a conversation."""
    conv_id = request.GET.get("conv_id")
    if not conv_id:
        return JsonResponse({"error": "Missing conv_id parameter"}, status=400)

    try:
        conversation = Conversation.objects.get(id=conv_id)
        messages = Message.objects.filter(conversation=conversation).order_by(
            "timestamp"
        )
        messages_data = [
            {"role": m.sender_role, "message": m.content} for m in messages
        ]

        return JsonResponse({"messages": messages_data})
    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)


def send_message(request):
    """Send a message in the conversation."""
    data = json.loads(request.body.decode("utf-8"))
    # ppt_id not used currently but might be needed in the future
    # ppt_id = data.get("ppt_id")
    conv_id = data.get("conversation_id")
    role = data.get("role")
    content = data.get("message")

    conversation = Conversation.objects.get(id=conv_id)
    if not conversation.can_send_message(role):
        raise ValueError(f"Role {role} cannot send message in conversation {conv_id}")

    user_message_sent = tz.now()

    # Save incoming message
    Message.objects.create(
        conversation_id=conv_id,
        sender_role=role,
        content=content,
        cost=0,
        timestamp=user_message_sent,
    )

    # Get response from GPT
    persuader = conversation.ai_persuader
    response = persuader.chat_response(conversation)

    # Store response
    Message.objects.create(
        conversation_id=conv_id,
        sender_role="P",
        content=response["message"],
        cost=response["cost"],
    )

    return JsonResponse({"success": True, "response": response, "type": "chat_message"})


def send_verdict(request):
    """Send a message in the conversation."""
    data = json.loads(request.body.decode("utf-8"))
    ppt_id = data.get("ppt_id")
    conv_id = data.get("conversation_id")

    # Create QuestionResponse object
    conversation = Conversation.objects.get(id=conv_id)
    question = Question.objects.get(id=conversation.question.id)
    ppt = Participant.objects.get(id=ppt_id)

    QuestionResponse.objects.create(
        participant=ppt,
        question=question,
        trial_index=conversation.trial_index,
        response=data.get("verdict"),
        confidence=data.get("confidence"),
        response_type="post",
        reason=data.get("reason"),
    )

    # Update Conversation (mark verdict)
    conversation = Conversation.objects.get(id=conv_id)
    conversation.end_time = tz.now()
    conversation.status = "verdict"
    conversation.save(update_fields=["end_time", "status"])

    # Broadcast decision event to WebSocket group
    channel_layer = get_channel_layer()
    group_name = f"conversation_{conv_id}"
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "decision.made",
        },
    )

    correct_answer = getattr(question, conversation.correct_answer)
    target_answer = data.get("verdict")
    is_correct = "Correct" if correct_answer == target_answer else "Incorrect"

    feedback = {
        "correct_answer": correct_answer,
        "target_answer": target_answer,
        "is_correct": is_correct,
    }
    print(feedback)

    return JsonResponse({"success": True, "feedback": feedback})


def get_ppt_accuracy(ppt):
    survey_questions = utils.load_survey_questions()
    for q in survey_questions:
        q["correct_answer_text"] = q[q["correct_answer"]]

    # Get question responses
    question_ids = [q["id"] for q in survey_questions]

    responses = QuestionResponse.objects.filter(
        participant=ppt, question__id__in=question_ids
    )
    print(responses)

    # Create a lookup dictionary keyed by (question_id, response_type)
    response_dict = {}
    for resp in responses:
        # For responses that are not pre or post, response_type might be None
        key = (resp.question.id, resp.response_type)
        response_dict[key] = resp.response

    print(response_dict)

    total_responses = 0
    total_correct = 0

    # Loop over each survey question and add accuracy information.
    for q in survey_questions:
        correct = q["correct_answer_text"]
        # Check for a pre-conversation response.
        pre_key = (q["id"], "pre")
        if pre_key in response_dict:
            pre_resp = response_dict[pre_key]
            q["pre_accuracy"] = "Correct" if pre_resp == correct else "Incorrect"
            total_responses += 1
            if pre_resp == correct:
                total_correct += 1

        # Check for a post-conversation response.
        post_key = (q["id"], "post")
        if post_key in response_dict:
            post_resp = response_dict[post_key]
            q["post_accuracy"] = "Correct" if post_resp == correct else "Incorrect"
            total_responses += 1
            if post_resp == correct:
                total_correct += 1

        # If neither pre nor post are present, look for a single (unspecified) response.
        no_type_key = (q["id"], None)
        if no_type_key in response_dict:
            resp_val = response_dict[no_type_key]
            q["accuracy"] = "Correct" if resp_val == correct else "Incorrect"
            total_responses += 1
            if resp_val == correct:
                total_correct += 1

    print(survey_questions)

    # Compute aggregate accuracy (as a percentage)
    aggregate_accuracy = (
        (total_correct / total_responses * 100) if total_responses > 0 else 0
    )
    aggregate_accuracy = round(aggregate_accuracy)

    print(aggregate_accuracy)

    return survey_questions, aggregate_accuracy


def get_participant_role(ppt):
    """Determine if participant was a target (T) or persuader (P)."""
    # Check if this participant was the target in any conversations
    target_conversations = Conversation.objects.filter(participant=ppt)
    if target_conversations.exists():
        return "T"

    # Check if this participant was the persuader in any conversations
    persuader_conversations = Conversation.objects.filter(human_persuader=ppt)
    if persuader_conversations.exists():
        return "P"

    return "unknown"


def get_actual_advisor_identity(ppt):
    """Determine the actual advisor identity (human or AI) for the participant."""
    # Get conversations where this participant was the target
    conversations = Conversation.objects.filter(participant=ppt)

    if not conversations.exists():
        return "unknown"

    # Check the first conversation to determine advisor type
    # (all conversations for a participant should have the same advisor type)
    first_conv = conversations.first()

    if first_conv.human_persuader:
        return "human"
    elif first_conv.ai_persuader:
        return "ai"
    else:
        return "unknown"


def exit_survey(request, ppt_id):
    """Render exit survey."""
    n_persuadability_questions = request.GET.get("n_persuadability_questions", None)
    n_persuadability_questions = (
        int(n_persuadability_questions) if n_persuadability_questions else None
    )

    ppt = Participant.objects.get(id=ppt_id)
    participant_role = get_participant_role(ppt)
    n_persuadability_questions = (
        n_persuadability_questions or ppt.n_persuadability_questions
    )
    persuadability_questions = utils.load_persuadability_questions(
        n_persuadability_questions
    )

    survey_questions, accuracy = get_ppt_accuracy(ppt)
    actual_advisor_identity = get_actual_advisor_identity(ppt)

    # Determine Prolific exit routing by participant status
    participant_status = ppt.status or "incomplete"
    prolific_exit_url = None
    if (ppt.source or "").lower() == "prolific":
        code_map = {
            "completed": "REDACTED",
            "abandoned": "REDACTED",
            "partner_abandoned": "REDACTED",
            "error": "REDACTED",
            "incomplete": "REDACTED",
        }
        code = code_map.get(participant_status, "REDACTED")
        prolific_exit_url = f"https://app.prolific.com/submissions/complete?cc={code}"

    # Include source and prolific completion routing to allow conditional exit behavior in template
    conf = {
        "ppt_id": ppt_id,
        "questions": persuadability_questions,
        "source": ppt.source,
        "prolific_exit_url": prolific_exit_url,
        "fast_exit": participant_status
        in [
            "abandoned",
            "partner_abandoned",
            "error",
        ],
    }
    context = {
        "conf": conf,
        "survey_questions": survey_questions,
        "accuracy": accuracy,
        "actual_advisor_identity": actual_advisor_identity,
        "participant_role": participant_role,
        "participant_status": participant_status,
    }
    print(context)
    return render(request, "conversation/exit_survey.html", context)


def save_exit_survey_results(request):
    """Save exit survey results to the database."""
    post = json.loads(request.body.decode("utf-8"))
    data = post["results"]
    ppt_id = post["ppt_id"]

    # Get or create participant object
    ppt, _ = Participant.objects.get_or_create(id=ppt_id)

    # ------------------------------
    # 1) Save Persuadability results
    # ------------------------------
    persuadability_trials = [
        item for item in data if item.get("item_type") == "persuasion_scale"
    ]
    for pt in persuadability_trials:
        response = pt.get("response")
        # Get the corresponding question object
        question = PersuadabilityQuestion.objects.get(item_id=pt.get("item_id"))
        # Create a new PersuadabilityResponse object
        PersuadabilityResponse.objects.create(
            participant=ppt,
            question=question,
            response=response["likert"],
            scoring=1 if question.scoring == "normal" else -1,
            reaction_time=pt.get("rt"),
        )

    # Determine completion status: all conversations must have verdicts
    try:
        from conversation.models import Conversation

        total_convs = Conversation.objects.filter(
            models.Q(participant=ppt) | models.Q(human_persuader=ppt)
        ).count()
        verdict_convs = Conversation.objects.filter(
            (models.Q(participant=ppt) | models.Q(human_persuader=ppt)),
            status="verdict",
        ).count()
        if total_convs and verdict_convs == total_convs:
            ppt.status = "completed"
    except Exception:
        # Do not fail save on status computation issues
        pass

    ppt.save()

    # ------------------------------
    # 2) Save Demographics
    # ------------------------------
    demos = [item for item in data if item.get("item_type") == "demographics"]
    if demos:
        demo_responses = demos[0].get("response", {})
        ppt.birth_year = demo_responses.get("demographics_year")
        ppt.gender = demo_responses.get("demographics_gender")
        ppt.native_english = demo_responses.get("demographics_english") == "yes"

    # ------------------------------
    # 3) Save Expertise
    # ------------------------------
    expertise = [item for item in data if item.get("item_type") == "expertise"]
    if expertise:
        exp_responses = expertise[0].get("response", {})
        ppt.physics = exp_responses.get("physics_expertise")
        ppt.logic = exp_responses.get("logic_expertise")
        ppt.ethics = exp_responses.get("ethics_expertise")
        ppt.policy = exp_responses.get("policy_expertise")
        ppt.probability = exp_responses.get("prob_expertise")

    # ------------------------------
    # 4) Save Model Evaluation Responses
    # ------------------------------
    model_eval = [item for item in data if item.get("item_type") == "model_evaluation"]
    if model_eval:
        eval_responses = model_eval[0].get("response", {})
        ppt.model_persuasiveness = eval_responses.get("persuasiveness")
        ppt.model_likeability = eval_responses.get("likeability")
        ppt.model_reliability = eval_responses.get("reliability")

    # ------------------------------
    # 5) Save Funnel Debrief Responses
    # ------------------------------
    funnel_debrief = [
        item for item in data if item.get("item_type") == "funnel_debrief"
    ]
    if funnel_debrief:
        funnel_responses = funnel_debrief[0].get("response", {})
        ppt.model_error_rate = funnel_responses.get("model_error_rate")
        ppt.model_incorrect_training = funnel_responses.get("model_incorrect_training")
        ppt.model_incorrect_instruction = funnel_responses.get(
            "model_incorrect_instruction"
        )
        # Use existing debrief field for any open-ended comments if provided.
        if funnel_responses.get("model_incorrect_open"):
            ppt.model_incorrect_open = funnel_responses.get("model_incorrect_open")

    # ------------------------------
    # 6) Save General Debrief and Sources (robust to single/multiple trials)
    # ------------------------------
    debrief_items = [item for item in data if item.get("item_type") == "debrief"]
    for item in debrief_items:
        resp = item.get("response", {}) or {}
        # Sources block
        if "consulted" in resp or "describe_sources" in resp:
            ppt.consulted = resp.get("consulted") == "yes"
            ppt.sources = resp.get("describe_sources")
        # Free-text debrief block
        if not ppt.debrief and "demographics_debrief" in resp:
            ppt.debrief = resp.get("demographics_debrief")

    # ------------------------------
    # 7) Save Human vs AI Detection Responses
    # ------------------------------
    human_vs_ai = [
        item for item in data if item.get("item_type") == "human_vs_ai_detection"
    ]
    if human_vs_ai:
        detection_responses = human_vs_ai[0].get("response", {})
        ppt.advisor_type = detection_responses.get("advisor_type")
        ppt.advisor_confidence = detection_responses.get("advisor_confidence")
        ppt.advisor_reasoning = detection_responses.get("advisor_reasoning")

    # ------------------------------
    # Update Participant End Time & Grant Credit if Applicable
    # ------------------------------
    ppt.end_time = tz.now()
    credit_granted = False
    if ppt.sona_code:
        credit_granted = grant_credit(ppt)

    ppt.save()
    return JsonResponse({"success": True, "credit_granted": credit_granted})


"""
Download Data
-------------
"""


def is_admin(user):
    """Check if user is an admin."""
    return user.is_superuser


def get_model_data(model_name):
    """Get data on all trials."""
    model = MODELS[model_name]

    data_list = []
    for record in model.objects.all():

        data = record.__dict__
        data.pop("_state")

        data_list.append(data)

    df = pd.DataFrame(data_list)
    df = df.sort_values("id").reset_index(drop=True)
    return df


@user_passes_test(is_admin)
def download_data(request, model):
    """Download csv of model data."""
    data = get_model_data(model)

    fname = f"{MODULE_URL}_{model}_{tz.now():%Y-%m-%d-%H-%M-%S}.csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{fname}"'

    data.to_csv(response, index=False)

    return response


def waiting_room(request):
    """Render waiting room page where participant waits to be matched."""
    ppt_id = request.GET.get("ppt_id")
    # Validate ppt_id; redirect to survey if missing/invalid
    try:
        if ppt_id is None:
            return redirect("/conversation/survey/")
        int(ppt_id)
    except Exception:
        return redirect("/conversation/survey/")
    return render(request, "conversation/waiting_room.html", {"ppt_id": ppt_id})


def waiting_room_timeout(request):
    """Convert ppt to ai interaction type and initiate game."""
    ppt_id = request.GET.get("ppt_id")
    ppt = Participant.objects.get(id=ppt_id)

    # Change interaction type to AI
    ppt.interaction_type = "human_ai"
    ppt.is_timeout_match = True
    ppt.save()

    # Redirect to conversation instructions
    return redirect(reverse("conversation") + f"?ppt_id={ppt.id}")
