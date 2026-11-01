import json
import random
import logging
import asyncio

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone as tz
from asgiref.sync import async_to_sync

# Remove model imports from module level - import them inside functions instead
# from conversation.models import Conversation, Message, Participant, Question

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


# Track active websocket connections per conversation id
active_connections = {}
afk_tasks = {}


# -------- helpers --------
@database_sync_to_async
def fetch_participant(ppt_id):
    from conversation.models import Participant

    return Participant.objects.get(id=ppt_id)


@database_sync_to_async
def pick_question():
    from conversation.models import Question

    return Question.objects.order_by("?").first()


@database_sync_to_async
def create_conversation(**kwargs):
    from conversation.models import Conversation

    return Conversation.objects.create(**kwargs)


@database_sync_to_async
def fetch_target_conversations(target_participant):
    """Fetch all conversations for the target participant to use as the shared sequence."""
    from conversation.models import Conversation

    return list(
        Conversation.objects.filter(
            participant=target_participant,
            ai_persuader__isnull=False,  # These are the pre-created AI conversations
            human_persuader__isnull=True,  # Not yet assigned to human persuader
            end_time__isnull=True,  # Not completed
        ).order_by("trial_index")
    )


@database_sync_to_async
def assign_human_persuader_to_conversations(conversations, persuader_participant):
    """Update target's conversations to assign human persuader and mark as human interaction."""
    from conversation.models import Conversation

    conversation_ids = [conv.id for conv in conversations]
    updated_count = Conversation.objects.filter(id__in=conversation_ids).update(
        human_persuader=persuader_participant,
        ai_persuader=None,  # Remove AI persuader
        persuader_is_human=True,
    )
    return updated_count


@database_sync_to_async
def delete_persuader_original_conversations(persuader_participant):
    """Delete the persuader's original conversation set to avoid conflicts."""
    from conversation.models import Conversation

    deleted_count = Conversation.objects.filter(
        participant=persuader_participant,
        ai_persuader__isnull=False,  # Original AI conversations
        human_persuader__isnull=True,  # Not yet assigned to human
        end_time__isnull=True,  # Not completed
    ).delete()
    return deleted_count[0] if deleted_count else 0


# Resume helpers
@database_sync_to_async
def get_existing_pairing_for_participant(ppt_id):
    """If participant already has an unfinished human-human conversation assignment,
    return (conversation, role) where role is 'T' or 'P'. Otherwise (None, None).
    """
    from django.db.models import Q
    from conversation.models import Conversation

    conv = (
        Conversation.objects.filter(end_time__isnull=True)
        .filter(
            Q(human_persuader_id=ppt_id)
            | Q(participant_id=ppt_id, human_persuader__isnull=False)
        )
        .order_by("trial_index")
        .first()
    )

    if not conv:
        return None, None

    role = "P" if conv.human_persuader_id == ppt_id else "T"
    return conv, role


# Simple in-memory waiting queue for participant IDs.
waiting_queue = []


class LobbyConsumer(AsyncWebsocketConsumer):
    """Temporary stub – matching logic will be added in a later step."""

    async def connect(self):
        await self.accept()
        await self.send(text_data=json.dumps({"type": "lobby", "status": "connected"}))

    async def disconnect(self, close_code):
        # Remove this participant from the waiting queue on disconnect
        try:
            ppt_id = getattr(self, "ppt_id", None)
            if ppt_id is not None:
                before = len(waiting_queue)
                # remove any entries with this ppt_id
                waiting_queue[:] = [
                    w for w in waiting_queue if str(w.get("ppt_id")) != str(ppt_id)
                ]
                after = len(waiting_queue)
                logger.info(
                    f"LobbyConsumer.disconnect: removed ppt_id={ppt_id} from queue (size {before}->{after})"
                )
        except Exception as e:
            logger.warning(f"LobbyConsumer.disconnect: error cleaning queue: {e}")

    async def receive(self, text_data=None, bytes_data=None):
        logger.info(f"LobbyConsumer: receive action received: {text_data}")
        data = json.loads(text_data or "{}")
        action = data.get("action")

        if action == "join":
            logger.info(f"LobbyConsumer: join action received")
            ppt_id = data.get("ppt_id")

            # Validate ppt_id (must be coercible to int)
            if ppt_id is None:
                await self.send(
                    text_data=json.dumps(
                        {"type": "error", "message": {"error": "ppt_id required"}}
                    )
                )
                return
            try:
                ppt_id_int = int(str(ppt_id).strip())
            except Exception:
                await self.send(
                    text_data=json.dumps(
                        {"type": "error", "message": {"error": "invalid ppt_id"}}
                    )
                )
                return

            # Keep ppt_id on the connection for cleanup later
            self.ppt_id = ppt_id_int

            # If this participant already has an unfinished human-human pairing, resume immediately
            existing_conv, role = await get_existing_pairing_for_participant(ppt_id_int)
            if existing_conv is not None:
                logger.info(
                    f"LobbyConsumer: resume existing pairing ppt_id={ppt_id_int} role={role} conv_id={existing_conv.id}"
                )
                await self.channel_layer.send(
                    self.channel_name,
                    {
                        "type": "lobby_paired",
                        "conv_id": existing_conv.id,
                        "role": role,
                    },
                )
                return

            # Add participant to waiting queue (dedupe by ppt_id; update channel if already present)
            existing = next(
                (w for w in waiting_queue if str(w.get("ppt_id")) == str(ppt_id_int)),
                None,
            )
            if existing:
                logger.info(
                    f"LobbyConsumer: updating channel for existing ppt_id={ppt_id_int} in queue"
                )
                existing["channel_name"] = self.channel_name
            else:
                waiting_queue.append(
                    {"ppt_id": ppt_id_int, "channel_name": self.channel_name}
                )

            # If at least 2 waiting, pair them
            logger.info(f"LobbyConsumer: waiting queue: {waiting_queue}")
            if len(waiting_queue) >= 2:
                first = waiting_queue.pop(0)
                # Ensure the next participant is not the same ppt_id (defensive)
                second = None
                while waiting_queue:
                    candidate = waiting_queue.pop(0)
                    if str(candidate.get("ppt_id")) != str(first.get("ppt_id")):
                        second = candidate
                        break
                if second is None:
                    # Put the first back and wait for another participant
                    waiting_queue.insert(0, first)
                    logger.info(
                        "LobbyConsumer: only one unique participant available; waiting for another"
                    )
                    return
                logger.info(f"LobbyConsumer: pairing {first} and {second}")

                # Randomly assign persuader vs target
                persuader_info, target_info = (
                    (first, second) if random.random() < 0.5 else (second, first)
                )

                persuader = await fetch_participant(persuader_info["ppt_id"])
                target = await fetch_participant(target_info["ppt_id"])

                # Fetch target's existing conversation set to use for both participants
                target_conversations = await fetch_target_conversations(target)

                if not target_conversations:
                    # Target has no available conversations, send error
                    error_msg = {
                        "error": "No available conversations for target participant"
                    }
                    await self.channel_layer.send(
                        target_info["channel_name"],
                        {"type": "lobby_error", "message": error_msg},
                    )
                    await self.channel_layer.send(
                        persuader_info["channel_name"],
                        {"type": "lobby_error", "message": error_msg},
                    )
                    logger.error(f"No conversations available for target {target.id}")
                    return

                # Update target's conversations to assign the human persuader
                updated_count = await assign_human_persuader_to_conversations(
                    target_conversations, persuader
                )
                logger.info(
                    f"Updated {updated_count} conversations with human persuader"
                )

                # Delete persuader's original conversations to avoid conflicts
                deleted_count = await delete_persuader_original_conversations(persuader)
                logger.info(
                    f"Deleted {deleted_count} original conversations for persuader"
                )

                # Get the first conversation to start with
                first_conv = target_conversations[0]

                # Notify both participants to start with the first conversation
                for info, role in ((persuader_info, "P"), (target_info, "T")):
                    await self.channel_layer.send(
                        info["channel_name"],
                        {
                            "type": "lobby_paired",
                            "conv_id": first_conv.id,
                            "role": role,
                        },
                    )
                    logger.info(
                        f"LobbyConsumer: sent paired notification to {info['channel_name']}"
                    )

    # Handler to send paired notification to WebSocket client
    async def lobby_paired(self, event):
        logger.info(f"LobbyConsumer: lobby_paired event received: {event}")
        await self.send(
            text_data=json.dumps(
                {
                    "type": "paired",
                    "conv_id": event["conv_id"],
                    "role": event["role"],
                }
            )
        )
        logger.info(f"LobbyConsumer: sent paired notification to {self.channel_name}")

    # Handler to send error notification to WebSocket client
    async def lobby_error(self, event):
        logger.info(f"LobbyConsumer: lobby_error event received: {event}")
        await self.send(
            text_data=json.dumps(
                {
                    "type": "error",
                    "message": event["message"],
                }
            )
        )
        logger.info(f"LobbyConsumer: sent error notification to {self.channel_name}")


class ChatConsumer(AsyncWebsocketConsumer):
    """Handle messages within a single conversation (human-AI or human-human).

    Expects WebSocket path:  ws/conversation/<conv_id>/
    Client messages must be JSON with keys: action="chat", role, message.
    """

    async def connect(self):
        # conversation ID extracted from URL kwargs provided by routing.py
        self.conv_id = self.scope["url_route"]["kwargs"]["conv_id"]
        self.group_name = f"conversation_{self.conv_id}"

        # Join group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Bump active connection count and perform idempotent end checks
        active_connections[self.conv_id] = active_connections.get(self.conv_id, 0) + 1
        try:
            conv = await self.get_conversation(self.conv_id)
            if conv and conv.start_time and not conv.end_time:
                duration = (tz.now() - conv.start_time).total_seconds()
                if duration >= 300:
                    # Time limit reached; mark end
                    await self.mark_conversation_ended(self.conv_id, reason="timeout")
                # If human-human and no messages yet, schedule initial AFK for Target
                from conversation.models import Message

                if conv.human_persuader_id and not conv.ai_persuader_id:
                    await self.cancel_afk_timer(self.conv_id)
                    await self.schedule_afk_timer(self.conv_id)
        except Exception as e:
            logger.warning(f"ChatConsumer.connect end-check failed: {e}")

    async def disconnect(self, close_code):
        # Leave group
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        # Decrement active count and if none remain, mark abandoned if not already ended
        try:
            if self.conv_id in active_connections:
                active_connections[self.conv_id] = max(
                    0, active_connections[self.conv_id] - 1
                )
                if active_connections[self.conv_id] == 0:
                    conv = await self.get_conversation(self.conv_id)
                    if conv and not conv.end_time:
                        await self.mark_conversation_ended(
                            self.conv_id, reason="abandoned"
                        )
                        # Cancel any AFK timer as we've ended the conversation
                        await self.cancel_afk_timer(self.conv_id)
        except Exception as e:
            logger.warning(f"ChatConsumer.disconnect cleanup failed: {e}")

    async def receive(self, text_data=None, bytes_data=None):
        data = json.loads(text_data or "{}")
        if data.get("action") != "chat":
            return

        role = data.get("role")
        content = data.get("message")
        temp_id = data.get("temp_id")  # Get temporary ID for deduplication

        # Persist message and, if applicable, trigger AI response
        conversation = await self.get_conversation(self.conv_id)
        if not conversation:
            await self.send(text_data=json.dumps({"error": "Conversation not found."}))
            return

        if not await self.can_send_message(conversation, role):
            await self.send(
                text_data=json.dumps({"error": "Cannot send message at this time."})
            )
            return

        # Save user message
        await self.create_message(
            conversation_id=self.conv_id,
            sender_role=role,
            content=content,
            cost=0,
        )

        # Broadcast user message to group (include temp_id for deduplication)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.message",
                "role": role,
                "message": content,
                "cost": 0,
                "temp_id": temp_id,  # Pass through temp_id
            },
        )

        # Schedule/reset AFK timer for human-human conversations (no AI)
        try:
            if (
                conversation
                and conversation.human_persuader_id
                and not conversation.ai_persuader_id
            ):
                # Reset AFK timer on every message; expect the other role to respond within 180s
                await self.cancel_afk_timer(self.conv_id)
                await self.schedule_afk_timer(self.conv_id)
        except Exception as e:
            logger.warning(f"AFK scheduling failed for conv {self.conv_id}: {e}")

        # If persuader is an AI and the user was the Target (T), generate AI response.
        if role == "T" and await self.has_ai_persuader(conversation):
            response = await self.get_ai_response(conversation)

            # Calculate typing delay based on message length and AI model settings
            ai_persuader = await self.get_ai_persuader(conversation)
            if ai_persuader.secs_per_char > 0:
                delay = len(response["message"]) * ai_persuader.secs_per_char
                logger.info(
                    f"AI typing delay: {delay:.2f}s for {len(response['message'])} chars"
                )
                await asyncio.sleep(delay)

            # Store response in DB
            await self.create_message(
                conversation_id=self.conv_id,
                sender_role="P",
                content=response["message"],
                cost=response["cost"],
            )

            # Broadcast AI response
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "chat.message",
                    "role": "P",
                    "message": response["message"],
                    "cost": response["cost"],
                },
            )

    async def chat_message(self, event):
        """Group event handler – sends message JSON to WebSocket client"""
        await self.send(text_data=json.dumps(event))

    async def decision_made(self, event):
        """Group event handler – sends decision notification to WebSocket client"""
        # Cancel AFK timer on decision
        await self.cancel_afk_timer(self.conv_id)
        await self.send(text_data=json.dumps(event))

    async def conversation_ended(self, event):
        # Group event handler to notify clients of AFK/timeout ends
        await self.send(
            text_data=json.dumps(
                {"type": "conversation.ended", "reason": event.get("reason")}
            )
        )

    # Async database helper methods
    @database_sync_to_async
    def get_conversation(self, conv_id):
        try:
            from conversation.models import Conversation

            return Conversation.objects.get(id=conv_id)
        except Conversation.DoesNotExist:
            return None

    @database_sync_to_async
    def mark_conversation_ended(self, conv_id, reason="unknown"):
        from conversation.models import Conversation

        try:
            conv = Conversation.objects.get(id=conv_id)
            if conv.end_time is None:
                conv.end_time = tz.now()
                if reason == "verdict":
                    conv.status = "verdict"
                else:
                    conv.status = "finished"
                conv.save(update_fields=["end_time", "status"])
                logger.info(
                    f"Conversation {conv_id} ended ({reason}) -> status={conv.status}"
                )
        except Conversation.DoesNotExist:
            return

    # AFK: end remaining conversations for both participants in this pairing
    @database_sync_to_async
    def end_all_remaining_for_pair(self, conv_id, reason="afk"):
        from django.db import models
        from conversation.models import Conversation, Participant, Message

        try:
            ref = Conversation.objects.get(id=conv_id)
        except Conversation.DoesNotExist:
            return 0
        now = tz.now()
        qs = Conversation.objects.filter(end_time__isnull=True).filter(
            models.Q(participant_id=ref.participant_id)
            | models.Q(human_persuader_id=ref.human_persuader_id)
        )
        updated = 0
        for c in qs:
            if c.status not in ("abandoned", "skipped", "verdict", "finished"):
                c.status = "abandoned" if c.id == conv_id else "skipped"
                c.save(update_fields=["status"])
                updated += 1
        # Infer AFK participant from last message sender: opposite role is AFK
        try:
            last_role = (
                Message.objects.filter(conversation_id=conv_id)
                .order_by("-timestamp")
                .values_list("sender_role", flat=True)
                .first()
            )
            afk_pid = None
            if last_role is None:
                # No messages sent; Target (participant) is expected to start
                afk_pid = ref.participant_id
            elif last_role == "T":
                afk_pid = ref.human_persuader_id  # P expected to reply
            elif last_role == "P":
                afk_pid = ref.participant_id  # T expected to reply

            for pid in [ref.participant_id, ref.human_persuader_id]:
                if not pid:
                    continue
                p = Participant.objects.get(id=pid)
                if p.status == "completed":
                    continue
                if afk_pid and pid == afk_pid:
                    p.status = "abandoned"
                else:
                    p.status = "partner_abandoned"
                p.save(update_fields=["status"])
        except Exception:
            pass
        logger.info(
            f"Ended {updated} conversations for pair due to {reason} from conv {conv_id}"
        )
        return updated

    # AFK timer helpers
    async def schedule_afk_timer(self, conv_id):
        async def timer_task():
            try:
                print("Sleeping for 180 seconds")
                await asyncio.sleep(180)
                print("Done sleeping")
                conv = await self.get_conversation(conv_id)
                print(f"Conv: {conv}")
                if not conv or conv.end_time:
                    return
                # Only act for human-human
                if not conv.human_persuader_id or conv.ai_persuader_id:
                    return
                # Cross-process safety: ensure no recent messages within 180s
                last_ts = await self.get_last_message_time(conv_id)
                print(f"Last message time: {last_ts}")
                if last_ts is not None:
                    if (tz.now() - last_ts).total_seconds() < 180:
                        return
                print("Ending all remaining for pair")
                await self.end_all_remaining_for_pair(conv_id, reason="afk")
                await self.channel_layer.group_send(
                    f"conversation_{conv_id}",
                    {"type": "conversation.ended", "reason": "afk"},
                )
            except Exception as e:
                logger.warning(f"AFK timer error for conv {conv_id}: {e}")

        # Cancel existing and schedule new
        await self.cancel_afk_timer(conv_id)
        task = asyncio.create_task(timer_task())
        afk_tasks[conv_id] = task

    async def cancel_afk_timer(self, conv_id):
        task = afk_tasks.get(conv_id)
        if task and not task.done():
            task.cancel()
        afk_tasks.pop(conv_id, None)

    @database_sync_to_async
    def get_last_message_time(self, conv_id):
        from conversation.models import Message

        ts = (
            Message.objects.filter(conversation_id=conv_id)
            .order_by("-timestamp")
            .values_list("timestamp", flat=True)
            .first()
        )
        return ts

    @database_sync_to_async
    def can_send_message(self, conversation, role):
        return conversation.can_send_message(role)

    @database_sync_to_async
    def create_message(self, **kwargs):
        from conversation.models import Message

        return Message.objects.create(**kwargs)

    @database_sync_to_async
    def has_ai_persuader(self, conversation):
        return conversation.ai_persuader is not None

    @database_sync_to_async
    def get_ai_response(self, conversation):
        return conversation.ai_persuader.chat_response(conversation)

    @database_sync_to_async
    def get_ai_persuader(self, conversation):
        return conversation.ai_persuader
