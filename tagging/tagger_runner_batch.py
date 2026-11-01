from tagger_utils import setup_logging, save, TagConfig, logger
from tagger_utils import client, format_conversation, parse_and_validate
from prompt_for_final_tagging import PROMPT_ALL, prompt_column_map
import pandas as pd
import json, time
import sys

setup_logging()

# chunk number from command line
CHUNK_ARG = int(sys.argv[1]) 

# from tagger_preprocessing.py
df_convos = pd.read_csv('data/input/convos_for_batch_rating.csv', header=0) 
df_convos = df_convos[df_convos.chunk == CHUNK_ARG]

# set config
cfg = TagConfig(reasoning='high')
file_suffix = f'55_high_final_chunk{CHUNK_ARG}'

# unique list of convos
convos = df_convos.conversation_id.unique().tolist()
logger.info(f'{len(convos)} convos')

output = {}
# create batch input file
path = f'data/output/batch_{cfg.label}_{file_suffix}.jsonl'

with open(path, 'w') as f:
    
    # for each convo, input line in input file
    for c in convos:
        body = {"model": cfg.mdl,
                "input": [{"role": "system", "content": PROMPT_ALL},
                            {"role": "user", "content": format_conversation(df_convos, c)}]}
        
        if cfg.tmp is not None:
            body["temperature"] = cfg.tmp
        if cfg.reasoning:
            body["reasoning"] = {"effort": cfg.reasoning}
        
        # custom_id set to conversation_id
        f.write(json.dumps({"custom_id": str(c), "method": "POST",
                            "url": "/v1/responses", "body": body}) + "\n")

# submit batch requests
fid = client.files.create(file=open(path, "rb"), purpose="batch").id
batch = client.batches.create(input_file_id=fid, endpoint="/v1/responses",
                                completion_window="24h")

logger.info(f'submitted {batch.id} ({len(convos)} convos)')

# poll every 60 seconds
while True:
    b = client.batches.retrieve(batch.id)
    logger.info(f'{b.status} {b.request_counts}')
    if b.status in ("completed", "failed", "expired", "cancelled"):
        break
    time.sleep(60)

if b.status == "completed":
    # once complete, parse output
    batch_out = client.files.content(b.output_file_id).text
    
    # for each line
    # parse and validate output, store in output dictionary keyed by conversation_id
    for line in batch_out.splitlines():
        
        rec = json.loads(line)
        
        # guard if any convo failed
        if rec.get("error") or rec.get("response") is None:
            output[rec["custom_id"]] = {'status': 'error', 'provably_false': False,
                'target_strategies': [], 'persuader_strategies': [], 'deception_strategies': []}
            continue 
            
        # if passed, set output key to conversation_id, and value to parsed and validated json text output
        # see tagger_utils.parse_and_validate           
        cid = rec["custom_id"]
        bod = rec["response"]["body"]
        text = bod.get("output_text") or "".join(
            p["text"] for it in bod.get("output", []) for p in it.get("content", [])
            if p.get("type") == "output_text")
        output[cid] = parse_and_validate(text)
        
else:
    logger.warning(f'ended as {b.status}: {b.errors}')

# set up dataframe with all entries default False
#   index = output.keys = conversation_id in order
#   columns = all original strategy outputs (n=50 for consistency to original runs)
columns = list(prompt_column_map.values())
df_llm = pd.DataFrame(False, index=output.keys(), columns=columns, dtype=bool)
df_llm["status"] = "good"

# for each conversation_id LLM output
for conv_id, out in output.items():
    
    # if error, return null ratings with status='error'
    if out.get('status') == 'error':
        df_llm.loc[conv_id, columns] = pd.NA
        df_llm.loc[conv_id, 'status'] = 'error'
        continue

    # otherwise, for each strategy tagged as present by LLM, set dataframe cell intersection
    # of conversation_id and strategy tag as True.
    for rating in (out.get('target_strategies', [])
            + out.get('persuader_strategies', [])
            + out.get('deception_strategies', [])):
        
        # redundant check to ensure all ratings are allowed
        if rating in prompt_column_map:
            df_llm.loc[conv_id, prompt_column_map[rating]] = True

    # returns provably_false bool
    if out.get('provably_false'):
        df_llm.loc[conv_id, 'deception_provably_false'] = True

# set index (conversation_id) to new conversation_id column
df_llm.insert(0, 'conversation_id', df_llm.index)
# set rater initials to LLM configuration label
df_llm.insert(1, 'rater_initials', cfg.label)
# bool -> int64
df_llm[columns] = df_llm[columns].astype('Int64')
# save output
save(df_llm, f'data/output/{cfg.label}_{file_suffix}.pkl')
