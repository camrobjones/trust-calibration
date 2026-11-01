"""Models for the conversation app."""

import logging
import time

from django.db import models
import openai
import together
from django.utils import timezone as tz

logger = logging.getLogger(__name__)
client = openai.OpenAI()
TogetherClient = together.Together()

MAX_MESSAGE_LEN = 300

INTRO_CONDITION_CHOICES = [(-1, "Unhelpful"), (0, "Neutral"), (1, "Helpful")]

FINAL_CONDITION_CHOICES = [(-1, "Unhelpful"), (1, "Helpful")]

FEEDBACK_CONDITION_CHOICES = [(0, "No feedback"), (1, "Feedback")]

HINT_CONDITION_CHOICES = [(0, "Interactive"), (1, "Hint")]

SYCPHANCY_CONDITION_CHOICES = [(-1, "Anti-Sycophancy"), (0, "Mixed"), (1, "Sycophancy")]

# Interaction types for experiment modes
INTERACTION_TYPE_CHOICES = [
    ("human_ai", "Human–AI"),
    ("human_human", "Human–Human"),
]

PROMPT_TOKEN_COSTS = {
    "gpt-4": 0.03 / 1000,
    "gpt-3.5-turbo": 0.0015 / 1000,
    "eliza": 0,
    "gpt-4o-2024-08-06": 2.5 / 1e6,
    "gpt-4o": 2.5 / 1e6,
    "chatgpt-4o-latest": 2.5 / 1e6,
    "o1-2024-12-17": 15 / 1e6,
    "o3-mini-2025-01-31": 1.10 / 1e6,
    "gpt-4.5-preview-2025-02-27": 75 / 1e6,
    "o3-2025-04-16": 2 / 1e6,
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": 3.5 / 1e6,
    "gpt-5-2025-08-07": 1.125 / 1e6,
}

COMPLETION_TOKEN_COSTS = {
    "gpt-4": 0.06 / 1000,
    "gpt-3.5-turbo": 0.003 / 1000,
    "eliza": 0,
    "gpt-4o-2024-08-06": 10 / 1e6,
    "gpt-4o": 10 / 1e6,
    "chatgpt-4o-latest": 10 / 1e6,
    "o1-2024-12-17": 60 / 1e6,
    "o3-mini-2025-01-31": 4.40 / 1e6,
    "gpt-4.5-preview-2025-02-27": 150 / 1e6,
    "o3-2025-04-16": 8 / 1e6,
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": 3.5 / 1e6,
    "gpt-5-2025-08-07": 10 / 1e6,
}


def calculate_costs(model_name, prompt_tokens, completion_tokens):
    prompt_cost = prompt_tokens * PROMPT_TOKEN_COSTS.get(model_name, 0)
    completion_cost = completion_tokens * COMPLETION_TOKEN_COSTS.get(model_name, 0)
    return prompt_cost + completion_cost


class Question(models.Model):
    """Class to store question data."""

    item_id = models.IntegerField(default=0, unique=True)
    category = models.TextField()
    subcategory = models.TextField()
    name = models.TextField()
    question = models.TextField()
    answer1 = models.TextField()
    answer2 = models.TextField()
    correct_answer = models.TextField()


class PersuadabilityQuestion(models.Model):
    """Class to store persuadbility question data."""

    item_id = models.IntegerField(default=0, unique=True)
    category = models.TextField()
    subcategory = models.TextField()
    question = models.TextField()
    scoring = models.TextField()


class Participant(models.Model):
    """Class to store participant data."""

    # Identifiers
    sona_code = models.TextField(default="", blank=True, null=True)
    prolific_id = models.TextField(default="", blank=True, null=True)
    source = models.TextField(default="", blank=True, null=True)  # E.g. SONA, Prolific
    study = models.CharField(max_length=80, blank=True, null=True)  # Pilot? Test? Main?

    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(default="", blank=True, null=True)
    # Session status tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ("incomplete", "Incomplete"),
            ("completed", "Completed"),
            ("abandoned", "Abandoned"),
            ("partner_abandoned", "Partner Abandoned"),
            ("error", "Error"),
        ],
        default="incomplete",
    )
    last_updated = models.DateTimeField(auto_now=True)

    # Demographics
    birth_year = models.IntegerField(blank=True, null=True)
    gender = models.CharField(blank=True, null=True, max_length=2)
    native_english = models.BooleanField(blank=True, null=True)

    # Expertise
    physics = models.IntegerField(blank=True, null=True)
    logic = models.IntegerField(blank=True, null=True)
    ethics = models.IntegerField(blank=True, null=True)
    policy = models.IntegerField(blank=True, null=True)
    probability = models.IntegerField(blank=True, null=True)

    # Model incorrect
    model_persuasiveness = models.IntegerField(blank=True, null=True)
    model_likeability = models.IntegerField(blank=True, null=True)
    model_reliability = models.IntegerField(blank=True, null=True)
    model_error_rate = models.IntegerField(blank=True, null=True)
    model_incorrect_training = models.IntegerField(blank=True, null=True)
    model_incorrect_instruction = models.IntegerField(blank=True, null=True)
    model_incorrect_open = models.TextField(default="", blank=True, null=True)

    # Human vs AI Detection
    advisor_type = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="'human' or 'ai' - participant's assessment",
    )
    advisor_confidence = models.IntegerField(
        blank=True, null=True, help_text="1-7 scale confidence in assessment"
    )
    advisor_reasoning = models.TextField(
        default="", blank=True, null=True, help_text="Explanation for assessment"
    )

    # Conditions
    intro_condition = models.IntegerField(
        choices=INTRO_CONDITION_CHOICES, blank=True, null=True
    )
    final_condition = models.IntegerField(
        choices=FINAL_CONDITION_CHOICES, blank=True, null=True
    )
    feedback_condition = models.IntegerField(
        choices=FEEDBACK_CONDITION_CHOICES,
        blank=True,
        null=True,
        default=1,
    )
    hint_condition = models.IntegerField(
        choices=HINT_CONDITION_CHOICES,
        blank=True,
        null=True,
        default=0,
    )

    sycophancy_condition = models.IntegerField(
        choices=SYCPHANCY_CONDITION_CHOICES,
        blank=True,
        null=True,
        default=0,
    )

    n_survey_questions = models.IntegerField(blank=True, null=True)
    n_persuadability_questions = models.IntegerField(blank=True, null=True)
    n_conversations = models.IntegerField(blank=True, null=True)
    questions_balanced = models.BooleanField(default=False)

    # Debrief / external sources
    consulted = models.BooleanField(blank=True, null=True)
    sources = models.TextField(default="", blank=True, null=True)
    debrief = models.TextField(default="")

    # What sort of interaction this participant will experience
    interaction_type = models.CharField(
        max_length=12,
        choices=INTERACTION_TYPE_CHOICES,
        default="human_ai",
    )

    is_timeout_match = models.BooleanField(
        default=False,
        help_text="True if this conversation was created due to waiting room "
        "timeout conversion to AI.",
    )

    def __str__(self):
        return f"Participant {self.id}"

    def total_cost(self):
        """Calculate the total cost across all conversations for this participant."""
        result = Message.objects.filter(conversation__participant=self).aggregate(
            total=models.Sum("cost")
        )
        return result["total"] or 0


class QuestionResponse(models.Model):
    """Responses to survey trial questions."""

    RESPONSE_TYPES = [
        ("pre", "Pre-conversation"),
        ("post", "Post-conversation"),
    ]

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)

    # Item identifier
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, null=True, blank=True
    )
    trial_index = models.IntegerField()  # Index for ppt
    created = models.DateTimeField(auto_now_add=True)
    response_type = models.CharField(
        max_length=4, choices=RESPONSE_TYPES, default="pre"
    )

    # Response info
    response = models.TextField(blank=True, default="")  # Ppt response
    confidence = models.IntegerField(blank=True, null=True)
    agreement = models.IntegerField(blank=True, null=True)
    reason = models.TextField(default="", blank=True)

    # Accuracy
    reaction_time = models.FloatField(blank=True, null=True)


class PersuadabilityResponse(models.Model):
    """Responses to persuadbility questions."""

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)

    # Item identifier
    question = models.ForeignKey(
        PersuadabilityQuestion, on_delete=models.CASCADE, null=True, blank=True
    )
    created = models.DateTimeField(auto_now_add=True)

    # Response info
    response = models.IntegerField(blank=True, null=True)  # 1-7 scale
    scoring = models.IntegerField(blank=True, null=True)  # 1 or -1
    reaction_time = models.FloatField(blank=True, null=True)


class AIPersuader(models.Model):
    """LLM-based persuader model."""

    name = models.CharField(max_length=100, blank=True, null=True)
    model_name = models.CharField(max_length=100, blank=True, null=True)
    active = models.BooleanField(default=True)
    prompt = models.TextField(blank=True, null=True)
    temperature = models.FloatField(default=0)
    secs_per_char = models.FloatField(default=0.0)
    max_length = models.IntegerField(default=100)
    response_method = models.CharField(max_length=100, default="openai_response")

    def chat_response(self, conversation):
        if self.response_method == "openai_response":
            return self.openai_response(conversation)
        if self.response_method == "togetherai_response":
            return self.togetherai_response(conversation)

    def format_question_message(self, conversation):

        question = conversation.question
        persuader_answer = getattr(question, conversation.persuader_answer)

        return {
            "role": "system",
            "content": (
                f"Question: {question.question}\n"
                f"Choices: [{question.answer1}, {question.answer2}]\n"
                f"Your answer: {persuader_answer}\n"
            ),
        }

    def format_messages(self, conversation):
        messages = [{"role": "system", "content": self.prompt}]

        # Only include previous conversations that have finished
        previous_convos = (
            Conversation.objects.filter(
                participant=conversation.participant,
                ai_persuader=self,
                end_time__isnull=False,
            )
            .exclude(pk=conversation.pk)
            .order_by("trial_index")
        )

        for prev in previous_convos:
            # Use the formatted question message as header
            messages.append(self.format_question_message(prev))
            for msg in prev.messages.all():
                role = "user" if msg.sender_role == "T" else "assistant"
                messages.append({"role": role, "content": msg.content})

        # Add current conversation context
        messages.append(self.format_question_message(conversation))
        for msg in conversation.messages.all():
            role = "user" if msg.sender_role == "T" else "assistant"
            messages.append({"role": role, "content": msg.content})

        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            print(f"[{role}] {content}")

        return messages

    def call_openai_api(self, formatted_messages):

        if (
            self.model_name.startswith("o1")
            or self.model_name.startswith("o3")
            or self.model_name.startswith("gpt-5")
        ):
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=formatted_messages,
                timeout=30,
                reasoning_effort="low",
                # max_completion_tokens=self.max_length,
            )
            # print(completion)
        else:
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=formatted_messages,
                temperature=self.temperature,
                max_tokens=self.max_length,
                timeout=30,
            )
        return completion

    def openai_response(self, game, retries=0):
        formatted_messages = self.format_messages(game)
        print(formatted_messages)

        completion = None

        for attempt in range(retries):
            if completion:
                break

            try:
                completion = self.call_openai_api(formatted_messages)
            except openai.RateLimitError as e:
                logger.warning("OpenAI API rate limit exceeded.")
                # Re-raise error
                raise e
            except Exception as e:
                logger.warning(f"OpenAI API error: {e}")
                backoff = (attempt + 1) ** 2
                logger.info(f"Sleeping for {backoff}s...")
                time.sleep(backoff)

        if not completion:
            # Final attempt, outside try to bubble error
            completion = self.call_openai_api(formatted_messages)
        print(completion.choices[0])
        message = completion.choices[0].message.content

        if len(message) > MAX_MESSAGE_LEN:
            logger.warning(
                "Message length (%d) exceeds max (%d). Trimming.",
                len(message),
                MAX_MESSAGE_LEN,
            )
            message = message[:MAX_MESSAGE_LEN]

        print(f"Prompt tokens: {completion.usage.prompt_tokens}")
        print(f"Completion tokens: {completion.usage.completion_tokens}")

        cost = calculate_costs(
            self.model_name,
            completion.usage.prompt_tokens,
            completion.usage.completion_tokens,
        )
        print(f"Cost: ${cost:.3f}")

        return {"message": message, "cost": cost}

    def call_togetherai_api(self, formatted_messages):
        completion = TogetherClient.chat.completions.create(
            model=self.model_name,
            messages=formatted_messages,
            temperature=self.temperature,
            max_tokens=self.max_length,
        )
        return completion

    def togetherai_response(self, game, retries=0):
        formatted_messages = self.format_messages(game)
        print(formatted_messages)

        completion = None

        for attempt in range(retries):
            if completion:
                break

            try:
                completion = self.call_togetherai_api(formatted_messages)
            except together.error.RateLimitError as e:
                logger.warning("Together API rate limit exceeded.")
                # Re-raise error
                raise e
            except Exception as e:
                logger.warning(f"Together API error: {e}")
                backoff = (attempt + 1) ** 2
                logger.info(f"Sleeping for {backoff}s...")
                time.sleep(backoff)

        if not completion:
            # Final attempt, outside try to bubble error
            completion = self.call_togetherai_api(formatted_messages)
        print(completion.choices[0])
        message = completion.choices[0].message.content

        if len(message) > MAX_MESSAGE_LEN:
            logger.warning(
                "Message length (%d) exceeds max (%d). Trimming.",
                len(message),
                MAX_MESSAGE_LEN,
            )
            message = message[:MAX_MESSAGE_LEN]

        print(f"Prompt tokens: {completion.usage.prompt_tokens}")
        print(f"Completion tokens: {completion.usage.completion_tokens}")

        cost = calculate_costs(
            self.model_name,
            completion.usage.prompt_tokens,
            completion.usage.completion_tokens,
        )
        print(f"Cost: ${cost:.3f}")

        return {"message": message, "cost": cost}


class Conversation(models.Model):
    """Class to store conversation data."""

    TRIAL_TYPES = [("intro", "Introduction"), ("final", "Final")]
    ANSWERS = [("answer1", "Answer 1"), ("answer2", "Answer 2")]

    # Target participant (the person whose belief might change)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)

    # Persuader variants (exactly one should be non-null)
    ai_persuader = models.ForeignKey(
        AIPersuader, on_delete=models.CASCADE, null=True, blank=True
    )
    human_persuader = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="persuader_conversations",
    )

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, null=True, blank=True
    )
    trial_index = models.IntegerField(blank=True, null=True)

    # Condition info
    trial_type = models.CharField(max_length=5, choices=TRIAL_TYPES)
    persuader_answer = models.CharField(max_length=10, choices=ANSWERS)
    target_answer = models.CharField(max_length=10, choices=ANSWERS)
    correct_answer = models.CharField(max_length=10, choices=ANSWERS)

    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    # Conversation lifecycle status
    status = models.CharField(
        max_length=12,
        choices=[
            ("created", "Created"),
            ("started", "Started"),
            ("finished", "Finished"),
            ("verdict", "Verdict"),
            ("abandoned", "Abandoned"),
            ("skipped", "Skipped"),
            ("error", "Error"),
        ],
        default="created",
    )

    persuader_is_human = models.BooleanField(
        default=False,
        help_text="True if the persuader is a human participant rather than an AI.",
    )

    def total_cost(self):
        """Calculate the total cost of all messages in this conversation."""
        result = self.messages.aggregate(total=models.Sum("cost"))
        return result["total"] or 0

    def can_send_message(self, role):
        if not self.start_time:
            return False

        duration = (tz.now() - self.start_time).total_seconds()
        print(duration)
        if duration > 300:
            return False

        last_message = self.messages.order_by("timestamp").last()
        if last_message:
            print(last_message.sender_role, role)
            if last_message.sender_role == role:
                return False

        return True


class Message(models.Model):
    SENDER_ROLES = [
        ("P", "Persuader"),
        ("T", "Target"),
    ]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender_role = models.CharField(max_length=1, choices=SENDER_ROLES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    cost = models.FloatField(default=0)

    class Meta:
        ordering = ["timestamp"]
