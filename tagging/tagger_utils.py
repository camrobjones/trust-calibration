import logging
import json
import pickle
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
import os
from openai import OpenAI
from prompt_for_final_tagging import prompt_column_map

def load(path):
    with open(path, 'rb') as f:
        return pickle.load(f)

def save(obj, path):
    with open(path, 'wb') as f:
        pickle.dump(obj, f)
    logger.info(f'file saved to {path}')

def setup_logging(log_dir='_logs', name='pipeline'):
    Path(log_dir).mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(f'{log_dir}/{name}.log', mode='w'),
            logging.StreamHandler(),
        ],
        force=True,
    )
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('openai').setLevel(logging.WARNING)

# Load key
load_dotenv()
client = OpenAI(api_key=os.environ['OPENAI_API_KEY_SECRET'])

# Setup logging
logger = logging.getLogger(__name__)
setup_logging()

# Only keys from prompt column map are allowed in LLM output
ALLOWED_IN_LIST = set(prompt_column_map) - {'provably_false'}

# Dataclass for GPT configuration
@dataclass
class TagConfig:
    mdl: str = 'gpt-5.5' # Final model, GPT 5.5
    tmp: float = None
    reasoning: str = None # set as param in llm_tagger_zeroshot.py 
    @property
    def label(self): # label for output filename
        return (
            f"m{self.mdl.replace('-', '')}"
            f"_t{self.tmp if self.tmp is not None else -1}"
            f"_r{self.reasoning.title() if self.reasoning else 'None'}"
        )

def format_conversation(df_in, conversation_id):
    '''
    Formats conversation to pass to LLM prompt

    Args:
        df_in: dataframe with all conversations
        conversation_id: conversation_id to pass to LLM prompt

    Returns:
        Conversation details to append to end of LLM prompt instructions, including question-answer
        info and line-by-line transcription with role identification.
    '''

    # Filter main df to conversation_id, sort by message_id
    df_messages = (
        df_in[df_in.conversation_id == conversation_id]
        .sort_values('message_id')
        .reset_index(drop=True))
    # set question, answer1, answer2, persuader assigned answer to prepend to conversation
    question = df_messages.iloc[0]['question']
    answer1 = df_messages.iloc[0]['answer1']
    answer2 = df_messages.iloc[0]['answer2']
    persuader_answer = df_messages.iloc[0]['persuader_answer']

    transcript = (
        f"Question: {question}\nAnswer 1: {answer1}\nAnswer 2: {answer2}\n"
        f"Persuader assigned answer: {persuader_answer}\n\n"
    )
    # add each message sequentially, including sender role
    for i in range(len(df_messages)):
        message = df_messages.iloc[i]
        transcript += f"{message['sender_role']}: {message['content']}\n"

    # Return question/answer information and line-by-line transcript
    return transcript

def parse_and_validate(text):
    '''
    Parses LLM json response, ensures alignment with strategy categories and items as defined in
    llm_tagger_prompts_IRR.py. 

    Args:
        text: output from LLM

    Returns:
        Parsed object, along with status ('good', 'error') for each conversation.
    '''

    # Ensure all 3 strategy buckets are returned
    req = ('target_strategies', 'persuader_strategies', 'deception_strategies')

    try:
        obj = json.loads(text)
        ok = (
            # Make sure dictionary returned
            isinstance(obj, dict)
            # 3 keys matching strategy buckets or provably false
            and set(obj.keys()) == set(req) | {'provably_false'}
            # Returns list of strategies in each bucket
            and all(isinstance(obj[k], list) for k in req)
            # Each list item is a string and in the allowed strategy list (ALLOWED_IN_LIST)
            and all(isinstance(t, str) and t in ALLOWED_IN_LIST for k in req for t in obj[k])
            # Provably false is bool
            and isinstance(obj['provably_false'], bool)
        )
        # If not, append status=error for downstream filtering
        if not ok:
            logger.warning('issue, reporting nulls')

            return {'status': 'error', 'provably_false': False, **{k: [] for k in req}}
        
        obj['status'] = 'good'

        return obj
    
    # If any other error occurs, return status=error
    except Exception:
        logger.warning("issue, reporting nulls")

        return {'status': 'error', 'provably_false': False, **{k: [] for k in req}}
